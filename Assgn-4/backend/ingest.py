# ingest.py — Content ingestion: web scraping, PDF extraction, YouTube transcript

import httpx
from bs4 import BeautifulSoup
import io
import re
from typing import Optional

# Try importing pypdf; graceful fallback if not installed
try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

# YouTube transcript fallback
try:
    from youtube_transcript_api import YouTubeTranscriptApi
    YT_TRANSCRIPT_AVAILABLE = True
except ImportError:
    YT_TRANSCRIPT_AVAILABLE = False

from mcp_config import YOUTUBE_MCP_SERVER


# ── Chunking ───────────────────────────────────────────────────────────────
CHUNK_SIZE = 800      # characters
CHUNK_OVERLAP = 100


def chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks."""
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return [c.strip() for c in chunks if c.strip()]


# ── Dispatcher ─────────────────────────────────────────────────────────────
async def ingest_content(
    content_type: str,
    topic: str,
    source: str,
    content: Optional[str] = None,
    url: Optional[str] = None,
    title: Optional[str] = None,
) -> dict:
    """
    Main entry point. Returns {chunks: list[str], title: str, source: str}.
    Raises ValueError on failure.
    """
    if content_type == "text":
        if not content:
            raise ValueError("No content provided for type 'text'")
        return {
            "chunks": chunk_text(content),
            "title": title or source,
            "source": source,
        }

    elif content_type == "page":
        return await _ingest_url(url or source, provided_content=content, title=title)

    elif content_type == "youtube":
        yt_url = url or source
        return await _ingest_youtube(yt_url)

    else:
        raise ValueError(f"Unknown content type: {content_type}")


# ── Web page / PDF ingestion ───────────────────────────────────────────────
async def _ingest_url(url: str, provided_content: Optional[str] = None, title: Optional[str] = None) -> dict:
    """
    Fetch URL server-side. If Content-Type is PDF, extract with pypdf.
    Otherwise parse HTML with BeautifulSoup.
    Falls back to provided_content if fetch fails.
    """
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (Knowledge Collector)"})
            resp.raise_for_status()
            content_type_header = resp.headers.get("content-type", "")

            if "application/pdf" in content_type_header:
                return _extract_pdf(resp.content, url)
            else:
                return _extract_html(resp.text, url, title)

    except Exception as e:
        # Fallback to content injected by the extension
        if provided_content:
            return {
                "chunks": chunk_text(provided_content),
                "title": title or url,
                "source": url,
            }
        raise ValueError(f"Could not fetch URL '{url}': {e}")


def _extract_html(html: str, url: str, title: Optional[str] = None) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    # Remove noise
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()

    page_title = title or (soup.title.string.strip() if soup.title else url)

    # Try <main> or <article> first, fall back to <body>
    main = soup.find("main") or soup.find("article") or soup.body
    raw = main.get_text(separator=" ") if main else soup.get_text(separator=" ")
    cleaned = re.sub(r"\s+", " ", raw).strip()

    return {"chunks": chunk_text(cleaned), "title": page_title, "source": url}


def _extract_pdf(pdf_bytes: bytes, url: str) -> dict:
    if not PYPDF_AVAILABLE:
        raise ValueError("pypdf is not installed. Run: pip install pypdf")

    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages_text = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages_text.append(text)

    full_text = "\n".join(pages_text)
    full_text = re.sub(r"\s+", " ", full_text).strip()
    title = url.split("/")[-1] or url

    return {"chunks": chunk_text(full_text), "title": title, "source": url}


# ── YouTube ingestion ──────────────────────────────────────────────────────
async def _ingest_youtube(url: str) -> dict:
    video_id = _extract_youtube_id(url)
    if not video_id:
        raise ValueError(f"Could not extract video ID from URL: {url}")

    # Try external YouTube MCP server first (if configured)
    if YOUTUBE_MCP_SERVER.get("enabled"):
        try:
            return await _ingest_youtube_via_mcp(video_id, url)
        except Exception as e:
            print(f"[YouTube MCP] Failed ({e}), falling back to transcript API")

    # Fallback: youtube-transcript-api
    if not YT_TRANSCRIPT_AVAILABLE:
        raise ValueError(
            "youtube-transcript-api is not installed. Run: pip install youtube-transcript-api\n"
            "Or configure YOUTUBE_MCP_SERVER in mcp_config.py"
        )

    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        full_text = " ".join(entry["text"] for entry in transcript_list)
        full_text = re.sub(r"\s+", " ", full_text).strip()
        return {
            "chunks": chunk_text(full_text),
            "title": f"YouTube: {video_id}",
            "source": url,
        }
    except Exception as e:
        raise ValueError(f"Could not get YouTube transcript for {video_id}: {e}")


async def _ingest_youtube_via_mcp(video_id: str, url: str) -> dict:
    """
    Connect to the external YouTube MCP server and call its tool to get the transcript.
    Supports stdio (e.g., Docker, npx) and SSE transports based on mcp_config.py.
    """
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client, StdioServerParameters
    
    config = YOUTUBE_MCP_SERVER
    
    if config.get("transport") == "stdio":
        server_params = StdioServerParameters(
            command=config["command"],
            args=config.get("args", []),
            env={**os.environ, **config.get("env", {})}
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                # Call the tool (assuming it's named 'get_youtube_transcript' or similar)
                # You may need to adjust the tool name based on your specific MCP server
                result = await session.call_tool("get_youtube_transcript", {"video_id": video_id})
                
                if not result.content:
                    raise ValueError("MCP tool returned empty content")
                
                text_content = result.content[0].text
                return {
                    "chunks": chunk_text(text_content),
                    "title": f"YouTube: {video_id}",
                    "source": url,
                }
    else:
        raise NotImplementedError("Only stdio transport is currently implemented for MCP client fallback.")


def _extract_youtube_id(url: str) -> Optional[str]:
    """Extract video ID from various YouTube URL formats."""
    patterns = [
        r"(?:v=)([a-zA-Z0-9_-]{11})",
        r"(?:youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"(?:embed/)([a-zA-Z0-9_-]{11})",
        r"(?:shorts/)([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return None

import os, time, json, asyncio
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env") or load_dotenv(ROOT.parent / ".env")

import db
import providers as P
from router import Router, LIMITS, resolve, SHORTCUTS

DEFAULT_ORDER = ["ollama", "gemini", "nvidia", "groq", "cerebras", "openrouter", "github"]
ORDER = [x.strip() for x in os.getenv("LLM_ORDER", ",".join(DEFAULT_ORDER)).split(",") if x.strip()]
PORT = int(os.getenv("GATEWAY_PORT", "8099"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    app.state.providers = P.build_providers()
    app.state.router = Router(app.state.providers, ORDER)
    yield


app = FastAPI(title="LLM Gateway", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


class ChatRequest(BaseModel):
    messages: Optional[list] = None
    prompt: Optional[str] = None
    system: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    max_tokens: int = 2048
    temperature: float = 0.7
    stream: bool = False


def _normalize(req: ChatRequest):
    if req.messages:
        return req.messages
    msgs = []
    if req.system:
        msgs.append({"role": "system", "content": req.system})
    msgs.append({"role": "user", "content": req.prompt or ""})
    return msgs


def _est_tokens(messages, max_tokens):
    chars = sum(len(m.get("content", "")) for m in messages)
    return chars // 4 + max_tokens


def _attempts_str(attempts):
    return "; ".join(f"{a['provider']}:{a['reason']}" for a in attempts)


def _backoff_for(err: Exception) -> tuple[float, str]:
    """Returns (seconds, reason). Returns (0, '') if no backoff needed."""
    msg = str(err).lower()
    status = getattr(err, "status", None)
    if status == 429:
        if "queue_exceeded" in msg or "high traffic" in msg or "queue" in msg:
            return 15, "server queue full"
        if "quota" in msg or "rpm" in msg or "per minute" in msg:
            return 60, "RPM quota burned"
        if "rpd" in msg or "per day" in msg or "daily" in msg:
            return 3600, "RPD quota burned"
        return 30, "rate limited"
    if status and 500 <= status < 600:
        return 20, f"upstream {status}"
    if status == 408 or "timeout" in msg or "timed out" in msg:
        return 10, "timeout"
    if status == 401 or status == 403:
        return 600, "auth error"
    return 0, ""


@app.post("/v1/chat")
async def chat(req: ChatRequest):
    router = app.state.router
    messages = _normalize(req)
    prompt_text = "".join(m.get("content", "") for m in messages)
    est = _est_tokens(messages, req.max_tokens)
    explicit_override = bool(req.provider)

    candidates = router.candidates(req.provider) if req.provider else list(router.order)
    if req.provider and not candidates:
        raise HTTPException(400, f"unknown provider '{req.provider}'. Try one of: {list(router.providers)} or shortcuts {list(SHORTCUTS)}")

    all_attempts = []
    last_err = None

    for _ in range(len(candidates) + 1):
        name, atts = router.pick(est, candidates)
        all_attempts.extend(atts)
        if name is None:
            break

        provider = router.providers[name]
        t0 = time.time()
        router.state[name].record(0)

        try:
            if req.stream:
                async def gen():
                    try:
                        agg = []
                        async for chunk in provider.stream(messages, max_tokens=req.max_tokens, temperature=req.temperature, model=req.model):
                            agg.append(chunk)
                            yield f"data: {json.dumps({'provider': name, 'delta': chunk})}\n\n"
                        text = "".join(agg)
                        latency = int((time.time() - t0) * 1000)
                        in_tok = est - req.max_tokens
                        out_tok = len(text) // 4
                        router.state[name].tokens_today += in_tok + out_tok
                        router.state[name].tokens_minute.append((time.time(), in_tok + out_tok))
                        db.log_call(provider=name, model=req.model or provider.model,
                                    input_tokens=in_tok, output_tokens=out_tok,
                                    latency_ms=latency, status="ok",
                                    prompt_chars=len(prompt_text), response_chars=len(text),
                                    override=req.provider, attempted=_attempts_str(all_attempts))
                        yield f"data: {json.dumps({'done': True, 'provider': name})}\n\n"
                    except Exception as e:
                        db.log_call(provider=name, model=req.model or provider.model,
                                    status="error", error=str(e)[:500],
                                    latency_ms=int((time.time() - t0) * 1000),
                                    prompt_chars=len(prompt_text),
                                    override=req.provider, attempted=_attempts_str(all_attempts))
                        yield f"data: {json.dumps({'error': str(e)[:300]})}\n\n"

                return StreamingResponse(gen(), media_type="text/event-stream")

            result = await provider.chat(messages, max_tokens=req.max_tokens, temperature=req.temperature, model=req.model)
            latency = int((time.time() - t0) * 1000)
            tokens = (result["input_tokens"] or 0) + (result["output_tokens"] or 0)
            router.state[name].tokens_today += tokens
            router.state[name].tokens_minute.append((time.time(), tokens))
            db.log_call(provider=name, model=result["model"],
                        input_tokens=result["input_tokens"], output_tokens=result["output_tokens"],
                        latency_ms=latency, status="ok",
                        prompt_chars=len(prompt_text), response_chars=len(result["text"]),
                        override=req.provider, attempted=_attempts_str(all_attempts))
            return {
                "provider": name,
                "model": result["model"],
                "text": result["text"],
                "input_tokens": result["input_tokens"],
                "output_tokens": result["output_tokens"],
                "latency_ms": latency,
                "attempted": all_attempts,
            }

        except P.ProviderError as e:
            last_err = str(e)
            secs, reason = _backoff_for(e)
            if secs > 0:
                router.state[name].mark_unavailable(secs, reason)
            db.log_call(provider=name, model=req.model or provider.model,
                        status="error", error=str(e)[:500],
                        latency_ms=int((time.time() - t0) * 1000),
                        prompt_chars=len(prompt_text),
                        override=req.provider, attempted=_attempts_str(all_attempts))
            tag = f"failed: {str(e)[:100]}"
            if secs > 0:
                tag += f" → backoff {secs:.0f}s ({reason})"
            all_attempts.append({"provider": name, "reason": tag})
            if explicit_override or not getattr(e, "retryable", True):
                raise HTTPException(502, f"{name} failed: {e}")
            candidates = [c for c in candidates if c != name]
            continue
        except Exception as e:
            last_err = str(e)
            secs, reason = _backoff_for(e)
            if secs > 0:
                router.state[name].mark_unavailable(secs, reason)
            db.log_call(provider=name, model=req.model or provider.model,
                        status="error", error=str(e)[:500],
                        latency_ms=int((time.time() - t0) * 1000),
                        prompt_chars=len(prompt_text),
                        override=req.provider, attempted=_attempts_str(all_attempts))
            all_attempts.append({"provider": name, "reason": f"exception: {str(e)[:120]}"})
            if explicit_override:
                raise HTTPException(502, f"{name} failed: {e}")
            candidates = [c for c in candidates if c != name]
            continue

    raise HTTPException(503, f"all providers unavailable. attempts: {all_attempts}. last_error: {last_err}")


@app.get("/v1/providers")
async def list_providers():
    r = app.state.router
    return {
        "order": r.order,
        "providers": list(r.providers.keys()),
        "shortcuts": SHORTCUTS,
        "limits": LIMITS,
        "models": {n: p.model for n, p in r.providers.items()},
    }


@app.get("/v1/status")
async def status():
    r = app.state.router
    return {
        "order": r.order,
        "live": r.all_status(),
        "today": db.aggregate(),
        "limits": LIMITS,
    }


@app.get("/v1/calls")
async def calls(limit: int = 100, provider: Optional[str] = None, status: Optional[str] = None):
    return db.recent(limit=limit, provider=provider, status=status)


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(str(ROOT / "static" / "dashboard.html"))


@app.get("/help", response_class=HTMLResponse)
async def help_page():
    return FileResponse(str(ROOT / "static" / "help.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)

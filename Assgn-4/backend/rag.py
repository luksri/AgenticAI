# rag.py — ChromaDB RAG wrapper with Gemini embeddings

import os
import chromadb
from chromadb.utils.embedding_functions import GoogleGenerativeAiEmbeddingFunction
from datetime import datetime, timezone
from typing import Optional
import uuid


CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", "./chroma_db")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Single ChromaDB collection; topics are stored as metadata
COLLECTION_NAME = "knowledge_base"


def _get_client() -> chromadb.PersistentClient:
    return chromadb.PersistentClient(path=CHROMA_DB_PATH)


class LangChainOllamaEmbeddingFunction(chromadb.EmbeddingFunction):
    def __init__(self):
        from langchain_ollama import OllamaEmbeddings
        self.embeddings = OllamaEmbeddings(
            model="nomic-embed-text", 
        )
    def __call__(self, input: chromadb.Documents) -> chromadb.Embeddings:
        return self.embeddings.embed_documents(input)

def _get_collection(client: Optional[chromadb.PersistentClient] = None):
    c = client or _get_client()
    return c.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=LangChainOllamaEmbeddingFunction(),
        metadata={"hnsw:space": "cosine"},
    )


def add_documents(topic: str, chunks: list[str], source: str, title: str = "") -> int:
    """
    Embed and store text chunks under a topic.
    Returns the new total doc count for that topic.
    """
    if not chunks:
        return get_topic_doc_count(topic)

    collection = _get_collection()
    now = datetime.now(timezone.utc).isoformat()

    ids = [str(uuid.uuid4()) for _ in chunks]
    metadatas = [
        {
            "topic": topic,
            "source": source,
            "title": title or source,
            "timestamp": now,
        }
        for _ in chunks
    ]

    collection.add(documents=chunks, ids=ids, metadatas=metadatas)
    return get_topic_doc_count(topic)


def query(topic: Optional[str], query_text: str, k: int = 5) -> list[dict]:
    """
    Retrieve top-k relevant chunks. If topic is None, searches all topics.
    Returns list of {content, source, topic, title, score}.
    """
    collection = _get_collection()

    where = {"topic": topic} if topic else None

    results = collection.query(
        query_texts=[query_text],
        n_results=min(k, _safe_count(collection, where)),
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    docs = results["documents"][0] if results["documents"] else []
    metas = results["metadatas"][0] if results["metadatas"] else []
    distances = results["distances"][0] if results["distances"] else []

    return [
        {
            "content": doc,
            "source": meta.get("source", ""),
            "topic": meta.get("topic", ""),
            "title": meta.get("title", ""),
            "score": round(1 - dist, 4),  # cosine similarity
        }
        for doc, meta, dist in zip(docs, metas, distances)
    ]


def list_topics() -> list[dict]:
    """
    Return all unique topics with their doc count and unique source count.
    """
    collection = _get_collection()
    total = collection.count()
    if total == 0:
        return []

    # Fetch all metadata (no embedding needed)
    results = collection.get(include=["metadatas"])
    metas = results.get("metadatas", [])

    topic_map: dict[str, dict] = {}
    for m in metas:
        t = m.get("topic", "unknown")
        if t not in topic_map:
            topic_map[t] = {"name": t, "doc_count": 0, "sources": set(), "last_updated": ""}
        topic_map[t]["doc_count"] += 1
        topic_map[t]["sources"].add(m.get("source", ""))
        ts = m.get("timestamp", "")
        if ts > topic_map[t]["last_updated"]:
            topic_map[t]["last_updated"] = ts

    return [
        {
            "name": v["name"],
            "doc_count": v["doc_count"],
            "source_count": len(v["sources"]),
            "last_updated": v["last_updated"],
        }
        for v in sorted(topic_map.values(), key=lambda x: x["name"])
    ]


def get_topic_doc_count(topic: str) -> int:
    collection = _get_collection()
    return _safe_count(collection, {"topic": topic})


def get_stats() -> dict:
    """Global stats: total docs, total topics, total unique sources."""
    topics = list_topics()
    total_docs = sum(t["doc_count"] for t in topics)
    total_sources = sum(t["source_count"] for t in topics)
    return {
        "total_docs": total_docs,
        "total_topics": len(topics),
        "total_sources": total_sources,
        "topics": topics,
    }


def _safe_count(collection, where: Optional[dict]) -> int:
    """Count documents matching optional filter; avoid querying with n_results=0."""
    try:
        res = collection.get(where=where, include=[])
        return len(res.get("ids", []))
    except Exception:
        return collection.count()

"""
artifacts.py — Content-addressable blob store for large tool results.

Layout on disk:
    sandbox/state/artifacts/          ← raw blob files, named by their id
    sandbox/state/artifacts.json      ← metadata index  { art_id: Artifact }

The id is  "art:<first-16-hex-chars-of-sha256(blob)>".
That is short enough to embed in history dicts but unique enough
to avoid collisions at the scale a single student's agent reaches.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from schemas import Artifact

# ---------------------------------------------------------------------------
# Paths (relative to this file so the sandbox travels with the project)
# ---------------------------------------------------------------------------

_BASE = Path(__file__).parent / "sandbox" / "state"
_BLOBS_DIR = _BASE / "artifacts"
_INDEX_FILE = _BASE / "artifacts.json"


def _ensure_dirs() -> None:
    _BLOBS_DIR.mkdir(parents=True, exist_ok=True)
    if not _INDEX_FILE.exists():
        _INDEX_FILE.write_text("{}", encoding="utf-8")


def _load_index() -> dict[str, dict]:
    """Return the raw metadata dict from disk."""
    _ensure_dirs()
    text = _INDEX_FILE.read_text(encoding="utf-8").strip()
    return json.loads(text) if text else {}


def _save_index(index: dict[str, dict]) -> None:
    _INDEX_FILE.write_text(
        json.dumps(index, indent=2, default=str), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# ArtifactStore — the public interface
# ---------------------------------------------------------------------------

class ArtifactStore:
    """
    Content-addressable store for raw bytes produced by MCP tools.

    Roles interact with this store via:
        put()       — write bytes, get back an artifact id
        get_bytes() — retrieve bytes by id
        get_meta()  — retrieve Artifact metadata by id
        exists()    — check without loading bytes
    """

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def put(
        self,
        blob: bytes,
        *,
        content_type: str,
        source: str,
        descriptor: str,
    ) -> str:
        """
        Store *blob* and return its artifact id ("art:<16-hex>").

        If the same bytes were already stored the existing id is returned
        (content-addressable deduplication).
        """
        _ensure_dirs()

        sha = hashlib.sha256(blob).hexdigest()
        art_id = f"art:{sha[:16]}"

        # Deduplication: if content already stored, skip writing
        index = _load_index()
        if art_id not in index:
            blob_path = _BLOBS_DIR / art_id
            blob_path.write_bytes(blob)

            meta = Artifact(
                id=art_id,
                content_type=content_type,
                size_bytes=len(blob),
                source=source,
                descriptor=descriptor,
            )
            index[art_id] = meta.model_dump(mode="json")
            _save_index(index)

        return art_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_bytes(self, artifact_id: str) -> bytes:
        """Return the raw bytes for *artifact_id*.  Raises KeyError if missing."""
        blob_path = _BLOBS_DIR / artifact_id
        if not blob_path.exists():
            raise KeyError(f"Artifact not found: {artifact_id}")
        return blob_path.read_bytes()

    def get_meta(self, artifact_id: str) -> Artifact:
        """Return the Artifact metadata record.  Raises KeyError if missing."""
        index = _load_index()
        if artifact_id not in index:
            raise KeyError(f"Artifact not found: {artifact_id}")
        return Artifact(**index[artifact_id])

    def exists(self, artifact_id: str) -> bool:
        """Return True if the artifact is present in the store."""
        index = _load_index()
        return artifact_id in index


# ---------------------------------------------------------------------------
# Module-level singleton — imported by other roles
# ---------------------------------------------------------------------------

artifacts = ArtifactStore()
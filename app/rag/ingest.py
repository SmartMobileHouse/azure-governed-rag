"""Corpus ingestion: chunk → embed → upsert. Shared by the CLI and startup seed.

Kept identity-agnostic: it calls the same store/llm helpers as the request path,
so whatever identity runs it (the container's managed identity in Azure, or a
developer's `az login` locally) must hold the Cognitive Services OpenAI role.
"""

from __future__ import annotations

import logging
import os

from . import llm, store

log = logging.getLogger("app.ingest")

_SKIP = {"readme.md"}  # corpus notes, not content


def chunk_text(text: str, size: int = 800, overlap: int = 100) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start : start + size])
        start += size - overlap
    return chunks


def ingest_dir(dir_path: str) -> dict[str, int]:
    """Chunk, embed and upsert every .md/.txt file in dir_path.

    Idempotent per document (stable ids); returns {doc_id: chunk_count}.
    """
    store.init_schema()
    files = sorted(
        f
        for f in os.listdir(dir_path)
        if f.endswith((".md", ".txt")) and f.lower() not in _SKIP
    )
    result: dict[str, int] = {}
    for fname in files:
        path = os.path.join(dir_path, fname)
        doc_id = os.path.splitext(fname)[0]
        with open(path, encoding="utf-8") as fh:
            pieces = chunk_text(fh.read())
        if not pieces:
            continue
        embeddings = llm.embed(pieces)
        chunks = [
            {
                "ordinal": i,
                "content": piece,
                "embedding": emb,
                "metadata": {"source": fname, "title": doc_id},
            }
            for i, (piece, emb) in enumerate(zip(pieces, embeddings))
        ]
        result[doc_id] = store.upsert_document(doc_id, chunks)
    return result


def seed_if_empty(dir_path: str) -> dict[str, int]:
    """Seed the bundled corpus only when the store has no chunks yet.

    Lets a fresh deploy answer /chat out of the box; a no-op once anything is
    ingested (including a real corpus), so it never clobbers user data.
    """
    if not os.path.isdir(dir_path):
        log.info("seed skipped: %s not found", dir_path)
        return {}
    if store.count() > 0:
        return {}
    log.info("empty store — seeding sample corpus from %s", dir_path)
    return ingest_dir(dir_path)

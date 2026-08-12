"""Ingest a folder of .md/.txt docs into pgvector (idempotent per document).

    uv run python scripts/ingest.py [--dir docs/sample-corpus]

Runs the schema + LangGraph checkpointer migrations, then chunks, embeds, and
upserts each file. Re-running replaces a document's chunks (stable ids), so it
is safe to run repeatedly. File-upload UI is intentionally out of scope for v1.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.rag import graph, llm, store


def chunk_text(text: str, size: int = 800, overlap: int = 100) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start : start + size])
        start += size - overlap
    return chunks


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="docs/sample-corpus")
    args = ap.parse_args()

    print("Running migrations (schema + checkpointer)…")
    store.init_schema()
    graph.setup_checkpointer()

    files = sorted(
        f for f in os.listdir(args.dir) if f.endswith((".md", ".txt"))
    )
    if not files:
        print(f"No .md/.txt files in {args.dir}")
        return

    for fname in files:
        path = os.path.join(args.dir, fname)
        doc_id = os.path.splitext(fname)[0]
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        pieces = chunk_text(text)
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
        n = store.upsert_document(doc_id, chunks)
        print(f"  {doc_id}: {n} chunks")

    print("Done.")


if __name__ == "__main__":
    main()

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

from app.rag import graph, ingest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="docs/sample-corpus")
    args = ap.parse_args()

    print("Running migrations (schema + checkpointer)…")
    graph.setup_checkpointer()  # ingest_dir handles the store schema

    result = ingest.ingest_dir(args.dir)
    if not result:
        print(f"No .md/.txt content in {args.dir}")
        return
    for doc_id, n in result.items():
        print(f"  {doc_id}: {n} chunks")
    print("Done.")


if __name__ == "__main__":
    main()

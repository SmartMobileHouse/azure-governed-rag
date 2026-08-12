"""pgvector-backed document store: schema, idempotent upsert, similarity search."""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from pgvector.psycopg import Vector, register_vector
from psycopg.types.json import Jsonb

from .. import db

log = logging.getLogger("app.store")

EMBED_DIM = 1536  # text-embedding-3-small

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS rag_chunks (
    id          text PRIMARY KEY,
    doc_id      text NOT NULL,
    ordinal     int  NOT NULL,
    content     text NOT NULL,
    embedding   vector({EMBED_DIM}) NOT NULL,
    metadata    jsonb NOT NULL DEFAULT '{{}}',
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rag_chunks_doc_id_idx ON rag_chunks (doc_id);
CREATE INDEX IF NOT EXISTS rag_chunks_embedding_idx
    ON rag_chunks USING hnsw (embedding vector_cosine_ops);
"""


def _connect():
    conn = db.connect()
    register_vector(conn)
    return conn


def init_schema() -> None:
    with _connect() as conn, conn.cursor() as cur:
        # The `vector` extension needs azure_pg_admin, so on Azure it is
        # provisioned by the deploy hook and the app's managed-identity role
        # can't (re)create it — tolerate that failure. Locally (docker superuser)
        # this creates it. Autocommit means a failed statement doesn't poison
        # the CREATE TABLE that follows.
        try:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except psycopg.Error as e:
            log.info("CREATE EXTENSION vector skipped (hook-provisioned on Azure): %s", e)
        cur.execute(_SCHEMA)


def count() -> int:
    """Number of stored chunks (0 on a fresh store). Assumes init_schema ran."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM rag_chunks")
        return int(cur.fetchone()[0])


def upsert_document(doc_id: str, chunks: list[dict[str, Any]]) -> int:
    """Replace all chunks for a document (idempotent re-index).

    Each chunk: {"ordinal": int, "content": str, "embedding": list[float],
    "metadata": dict}.
    """
    with _connect() as conn, conn.transaction(), conn.cursor() as cur:
        cur.execute("DELETE FROM rag_chunks WHERE doc_id = %s", (doc_id,))
        for c in chunks:
            cur.execute(
                """INSERT INTO rag_chunks (id, doc_id, ordinal, content, embedding, metadata)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    f"{doc_id}:{c['ordinal']}",
                    doc_id,
                    c["ordinal"],
                    c["content"],
                    # Wrap in Vector so it adapts to the pgvector type; a bare
                    # list would be sent as double precision[] and rejected.
                    Vector(c["embedding"]),
                    Jsonb(c.get("metadata", {})),
                ),
            )
    return len(chunks)


def delete_document(doc_id: str) -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM rag_chunks WHERE doc_id = %s", (doc_id,))


def similarity_search(query_embedding: list[float], k: int = 4) -> list[dict[str, Any]]:
    qv = Vector(query_embedding)  # adapt to pgvector; a bare list becomes float8[]
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT content, doc_id, ordinal, metadata,
                      1 - (embedding <=> %s) AS score
               FROM rag_chunks
               ORDER BY embedding <=> %s
               LIMIT %s""",
            (qv, qv, k),
        )
        rows = cur.fetchall()
    return [
        {"content": r[0], "doc_id": r[1], "ordinal": r[2], "metadata": r[3], "score": float(r[4])}
        for r in rows
    ]

"""Thread ownership + atomic HITL decision state.

A dedicated table binds each server-minted thread to the pseudonymous owner that
created it, and records a single terminal approve/reject decision. Ownership is
checked on every thread-scoped endpoint, and the decision uses a compare-and-set
so two concurrent approve/reject calls cannot both take effect.
"""

from __future__ import annotations

import logging

from . import db
from .hashing import pseudonym

log = logging.getLogger("app.threads")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    thread_id   text PRIMARY KEY,
    owner_hash  text NOT NULL,
    decision    text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    decided_at  timestamptz
);
"""


def init_schema() -> None:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(_SCHEMA)


def create(thread_id: str, principal: str | None) -> None:
    """Record ownership at thread creation. Tolerant of re-creation and of a
    transient DB error (an unrecorded thread simply fails later ownership checks,
    i.e. fails safe)."""
    try:
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO threads (thread_id, owner_hash) VALUES (%s, %s) "
                "ON CONFLICT (thread_id) DO NOTHING",
                (thread_id, pseudonym(principal, "actor")),
            )
    except Exception as e:  # noqa: BLE001
        log.warning("thread ownership not recorded (%s): %s", thread_id, e)


def exists(thread_id: str) -> bool:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM threads WHERE thread_id = %s", (thread_id,))
        return cur.fetchone() is not None


def is_owner(thread_id: str, principal: str) -> bool:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT owner_hash FROM threads WHERE thread_id = %s", (thread_id,))
        row = cur.fetchone()
    return bool(row) and row[0] == pseudonym(principal, "actor")


def try_decide(thread_id: str, decision: str) -> bool:
    """Atomically move a thread from undecided → decision. Returns True if THIS
    call set it (the winner); False if it was already decided (idempotent loser).
    The row-level ``WHERE decision IS NULL`` makes concurrent calls serialize."""
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE threads SET decision = %s, decided_at = now() "
            "WHERE thread_id = %s AND decision IS NULL RETURNING thread_id",
            (decision, thread_id),
        )
        return cur.fetchone() is not None


def decision(thread_id: str) -> str | None:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT decision FROM threads WHERE thread_id = %s", (thread_id,))
        row = cur.fetchone()
    return row[0] if row else None

"""Privacy-safe audit trail.

One row per turn transition (answered / blocked / pending / approved / rejected)
in a dedicated ``audit_log`` table — a separate store from the operational rag /
checkpoint tables. It records *what was decided*, never raw content or identity:

* prompt and answer are stored as keyed hashes + lengths, never plaintext
* actor and approver are pseudonymous (HMAC) hashes — no email/UPN
* sources are hashed (a corpus filename can itself be PII)
* the persisted governance object is rebuilt from a strict allowlist of
  structural fields — booleans, counts, PII categories, and reason *codes*; every
  free-text field (grounding reasons, error messages, matched terms) is dropped
* policy / prompt / model version stamps make a decision reproducible

Best-effort: a failed write is logged and never breaks a turn. Hashing uses
HMAC-SHA256 keyed by ``AUDIT_HASH_KEY`` when set (see app/hashing.py).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from psycopg.types.json import Jsonb

from .. import db
from ..config import settings
from ..hashing import content_hash, pseudonym
from ..versions import POLICY_VERSION, PROMPT_VERSION

log = logging.getLogger("app.audit")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id             uuid PRIMARY KEY,
    thread_id      text NOT NULL,
    decision       text NOT NULL,
    actor_hash     text,
    question_sha   text,
    question_len   int,
    answer_sha     text,
    answer_len     int,
    sources        jsonb NOT NULL DEFAULT '[]',
    governance     jsonb NOT NULL DEFAULT '{}',
    checkpoint_id  text,
    policy_version text,
    prompt_version text,
    model          text,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_log_thread_idx ON audit_log (thread_id, created_at);
"""

_READ_COLS = [
    "decision", "actor_hash", "question_sha", "question_len", "answer_sha",
    "answer_len", "sources", "governance", "checkpoint_id", "policy_version",
    "prompt_version", "model", "created_at",
]


def init_schema() -> None:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(_SCHEMA)


def _reason_codes(reason: str | None) -> list[str]:
    """Map a human approval reason to structural codes (no free text persisted)."""
    r = (reason or "").lower()
    codes = []
    if "low groundedness" in r:
        codes.append("low_groundedness")
    if "pii" in r:
        codes.append("pii")
    if "sensitive terms" in r:
        codes.append("sensitive_terms")
    return codes


def _drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def _safe_governance(gov: dict | None) -> dict:
    """Rebuild governance from a strict allowlist — structural fields only.

    Nothing derived from the prompt, answer, retrieved text, PII values, or an
    error message is copied; free-text reasons become codes and identities become
    hashes. This is an allowlist by construction: unknown keys are never persisted.
    """
    if not gov:
        return {}
    out: dict[str, Any] = {}

    ins = gov.get("input_shield")
    if isinstance(ins, dict):
        out["input_shield"] = _drop_none(
            {"ok": ins.get("ok"), "attack": ins.get("attack"), "status": ins.get("status")}
        )

    cs = gov.get("chunk_shield")
    if isinstance(cs, dict):
        quarantined = cs.get("quarantined")
        out["chunk_shield"] = _drop_none(
            {"ok": cs.get("ok"),
             "quarantined_count": len(quarantined) if isinstance(quarantined, list) else None,
             "status": cs.get("status")}
        )

    gr = gov.get("groundedness")
    if isinstance(gr, dict):
        out["groundedness"] = _drop_none(
            {"ok": gr.get("ok"), "grounded": gr.get("grounded"), "status": gr.get("status")}
        )

    pii = gov.get("pii")
    if isinstance(pii, dict):
        out["pii"] = _drop_none(
            {"ok": pii.get("ok"), "count": pii.get("count"),
             "categories": pii.get("categories"), "status": pii.get("status")}
        )

    ap = gov.get("approval")
    if isinstance(ap, dict):
        out["approval"] = _drop_none(
            {"required": ap.get("required"), "approved": ap.get("approved"),
             # approver arrives already pseudonymized from the graph; never re-copy
             # a raw approver, and fall back to hashing one only if present.
             "approver_hash": ap.get("approver_hash") or pseudonym(ap.get("approver"), "approver"),
             "reason_codes": _reason_codes(ap.get("reason")) or None}
        )
    return out


def record(
    *,
    thread_id: str,
    decision: str,
    actor: str | None = None,
    question: str | None = None,
    answer: str | None = None,
    sources: list[str] | None = None,
    governance: dict | None = None,
    checkpoint_id: str | None = None,
) -> None:
    """Write one audit event. Best-effort — never raises into the request path."""
    try:
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO audit_log (
                       id, thread_id, decision, actor_hash, question_sha, question_len,
                       answer_sha, answer_len, sources, governance, checkpoint_id,
                       policy_version, prompt_version, model)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    str(uuid.uuid4()),
                    thread_id,
                    decision,
                    pseudonym(actor, "actor"),
                    content_hash(question),
                    len(question) if question else None,
                    content_hash(answer),
                    len(answer) if answer else None,
                    Jsonb([pseudonym(s, "source") for s in (sources or [])]),
                    Jsonb(_safe_governance(governance)),
                    checkpoint_id,
                    POLICY_VERSION,
                    PROMPT_VERSION,
                    settings.azure_openai_chat_deployment,
                ),
            )
    except Exception as e:  # noqa: BLE001 - audit is best-effort
        log.warning("audit write skipped (thread=%s decision=%s): %s", thread_id, decision, type(e).__name__)


def for_thread(thread_id: str) -> list[dict[str, Any]]:
    """Return a thread's decision trail (privacy-safe fields), oldest first."""
    try:
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""SELECT {', '.join(_READ_COLS)}
                    FROM audit_log WHERE thread_id = %s ORDER BY created_at""",
                (thread_id,),
            )
            rows = cur.fetchall()
    except Exception as e:  # noqa: BLE001
        log.warning("audit read failed (thread=%s): %s", thread_id, type(e).__name__)
        return []
    events = []
    for r in rows:
        event = dict(zip(_READ_COLS, r))
        created = event.get("created_at")
        if created is not None:
            event["created_at"] = created.isoformat()
        events.append(event)
    return events

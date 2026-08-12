"""Privacy-safe audit trail (M3 slice 2).

One row per turn transition (answered / blocked / pending / approved / rejected)
in a dedicated ``audit_log`` table — a separate store from the operational rag /
checkpoint tables. It records *what was decided*, never raw content or identity:

* prompt and answer are stored as sha256 hashes + lengths, never plaintext
* the actor and approver are pseudonymous hashes (no email/UPN stored)
* sources (doc ids) and safety verdicts are safe structural metadata
* policy / prompt / model version stamps make a decision reproducible
* a checkpoint id correlates the event to the exact LangGraph state

Best-effort: a failed write is logged and never breaks a turn. The actor hash is
a plain sha256 (deterministic pseudonym) — a keyed HMAC with a Key Vault secret
would be stronger and is the documented hardening path.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from typing import Any

from psycopg.types.json import Jsonb

from .. import db
from ..config import settings
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


def _hash(text: str | None) -> str | None:
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


_SENSITIVE_TERMS_RE = re.compile(r"sensitive terms: ([^;]+)")


def _redact_reason(reason: str | None) -> str | None:
    """Replace matched sensitive-term literals (derived from the question) with
    just their count, so no question-derived text is persisted in the audit."""
    if not reason:
        return reason

    def _count(m: re.Match) -> str:
        n = len([t for t in m.group(1).split(",") if t.strip()])
        return f"sensitive terms matched ({n})"

    return _SENSITIVE_TERMS_RE.sub(_count, reason)


def _redact_governance(gov: dict | None) -> dict:
    """Copy the governance verdicts, stripping anything derived from raw input:
    the approver email becomes a hash and matched sensitive terms become a count."""
    if not gov:
        return {}
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in gov.items()}
    approval = out.get("approval")
    if isinstance(approval, dict):
        if approval.get("approver"):
            approval["approver_hash"] = _hash(approval.pop("approver"))
        if approval.get("reason"):
            approval["reason"] = _redact_reason(approval["reason"])
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
                    _hash(actor),
                    _hash(question),
                    len(question) if question else None,
                    _hash(answer),
                    len(answer) if answer else None,
                    Jsonb(sources or []),
                    Jsonb(_redact_governance(governance)),
                    checkpoint_id,
                    POLICY_VERSION,
                    PROMPT_VERSION,
                    settings.azure_openai_chat_deployment,
                ),
            )
    except Exception as e:  # noqa: BLE001 - audit is best-effort
        log.warning("audit write skipped (thread=%s decision=%s): %s", thread_id, decision, e)


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
        log.warning("audit read failed (thread=%s): %s", thread_id, e)
        return []
    events = []
    for r in rows:
        event = dict(zip(_READ_COLS, r))
        created = event.get("created_at")
        if created is not None:
            event["created_at"] = created.isoformat()
        events.append(event)
    return events

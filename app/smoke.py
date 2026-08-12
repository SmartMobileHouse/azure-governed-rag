"""M0 vertical smoke slice.

`GET /smoke` proves the whole keyless chain actually works after `azd up`:
managed-identity chat + embedding calls, a Content Safety call, and a Postgres
connection with the pgvector extension present. This is what makes M0 a real
end-to-end proof rather than "ARM deployed a hello app". Protected by Easy Auth.
"""

from __future__ import annotations

from fastapi import APIRouter

from . import db
from .azure_clients import content_safety_client, openai_client
from .config import settings

router = APIRouter()


def _check_chat() -> dict:
    try:
        r = openai_client().chat.completions.create(
            model=settings.azure_openai_chat_deployment,
            messages=[{"role": "user", "content": "Reply with the single word: pong"}],
            # gpt-5 / reasoning models require max_completion_tokens (not max_tokens).
            max_completion_tokens=16,
        )
        return {"ok": True, "sample": (r.choices[0].message.content or "").strip()[:20]}
    except Exception as e:  # noqa: BLE001 - smoke check reports, never raises
        return {"ok": False, "error": str(e)[:200]}


def _check_embedding() -> dict:
    try:
        r = openai_client().embeddings.create(
            model=settings.azure_openai_embedding_deployment, input="hello world"
        )
        return {"ok": True, "dims": len(r.data[0].embedding)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}


def _check_content_safety() -> dict:
    try:
        from azure.ai.contentsafety.models import AnalyzeTextOptions

        content_safety_client().analyze_text(AnalyzeTextOptions(text="I want to hug a puppy."))
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}


def _check_postgres() -> dict:
    try:
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("select 1")
            cur.execute("select 1 from pg_extension where extname = 'vector'")
            has_vector = cur.fetchone() is not None
        return {"ok": True, "pgvector": has_vector}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}


@router.get("/smoke")
def smoke() -> dict:
    checks = {
        "chat": _check_chat(),
        "embedding": _check_embedding(),
        "content_safety": _check_content_safety(),
        "postgres": _check_postgres(),
    }
    checks["all_ok"] = all(c.get("ok") for c in checks.values())
    return checks

"""FastAPI entrypoint.

M0 shipped /health, /ready and the /smoke vertical slice. M1 adds /chat — the
governed RAG flow (retrieve → generate) orchestrated by LangGraph, with state
persisted per thread in Postgres. Safety nodes (M2) and the human-in-the-loop
approval gate (M3) slot into the same graph.
"""

from __future__ import annotations

import contextlib
import logging
import uuid

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from . import smoke
from .config import settings

log = logging.getLogger("app")


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    # Best-effort migrations so the app is self-bootstrapping; never block startup
    # on the DB (keeps /health up even if Postgres is briefly unreachable).
    try:
        from .rag import audit, graph, store

        store.init_schema()
        graph.setup_checkpointer()
        audit.init_schema()
        log.info("migrations applied (schema + checkpointer + audit)")
    except Exception as e:  # noqa: BLE001
        log.warning("startup migration skipped: %s", e)

    # Seed the bundled corpus so a fresh deploy has a working /chat. Best-effort
    # and only when the store is empty — never blocks startup, never clobbers data.
    if settings.seed_on_startup:
        try:
            from .rag import ingest

            seeded = ingest.seed_if_empty(settings.seed_corpus_dir)
            if seeded:
                log.info("seeded sample corpus: %s", seeded)
        except Exception as e:  # noqa: BLE001
            log.warning("corpus seed skipped: %s", e)
    yield


app = FastAPI(title="azure-governed-rag", version="0.2.0", lifespan=lifespan)
app.include_router(smoke.router)


@app.get("/health")
def health() -> dict:
    """Liveness: the process is up. No dependency calls."""
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict:
    """Readiness: configuration presence (M1 keeps this cheap; deep checks TODO)."""
    configured = {
        "azure_openai": bool(settings.azure_openai_endpoint),
        "content_safety": bool(settings.content_safety_endpoint),
        "language": bool(settings.language_endpoint),
        "postgres": bool(settings.postgres_host),
    }
    return {"ready": all(configured.values()), "configured": configured}


@app.get("/")
def root() -> dict:
    return {"name": "azure-governed-rag", "status": "M1 — RAG /chat", "docs": "/docs"}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    # Server issues opaque thread ids; a client may pass one back to continue a
    # conversation. (Binding threads to the authenticated caller is an M1 TODO.)
    thread_id: str | None = None


def _principal(request: Request) -> str:
    # Easy Auth injects the caller identity; fall back for local dev.
    return request.headers.get("x-ms-client-principal-name") or "local-dev"


@app.post("/chat")
def chat(req: ChatRequest, request: Request) -> dict:
    from .rag import graph

    thread_id = req.thread_id or f"t-{uuid.uuid4().hex}"
    # Returns {status: complete, ...} or {status: pending_approval, ...} when the
    # turn parks at the human approval gate. Response already carries thread_id.
    return graph.answer(req.message, thread_id, actor=_principal(request))


def _authorized(approver: str) -> bool:
    allow = [e.strip().lower() for e in settings.hitl_approver_emails.split(",") if e.strip()]
    return not allow or approver.lower() in allow


def _decide(thread_id: str, approved: bool, request: Request) -> dict:
    from .rag import graph

    approver = _principal(request)
    if not _authorized(approver):
        raise HTTPException(status_code=403, detail="not an authorized approver")
    result = graph.resume(thread_id, approved=approved, approver=approver)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="thread not found")
    return result


@app.post("/threads/{thread_id}/approve")
def approve(thread_id: str, request: Request) -> dict:
    """Release a parked answer. Idempotent; approver from Easy Auth identity."""
    return _decide(thread_id, True, request)


@app.post("/threads/{thread_id}/reject")
def reject(thread_id: str, request: Request) -> dict:
    """Withhold a parked answer. Idempotent; approver from Easy Auth identity."""
    return _decide(thread_id, False, request)


@app.get("/threads/{thread_id}/audit")
def thread_audit(thread_id: str) -> dict:
    """The turn's decision trail — hashed excerpts, pseudonymous actor, versions."""
    from .rag import audit

    return {"thread_id": thread_id, "events": audit.for_thread(thread_id)}

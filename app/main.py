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

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import smoke
from .auth import is_approver, require_principal
from .config import settings

log = logging.getLogger("app")


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    # Best-effort migrations so the app is self-bootstrapping; never block startup
    # on the DB (keeps /health up even if Postgres is briefly unreachable).
    try:
        from . import threads
        from .rag import audit, graph, store

        store.init_schema()
        graph.setup_checkpointer()
        audit.init_schema()
        threads.init_schema()
        log.info("migrations applied (schema + checkpointer + audit + threads)")
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


@app.post("/chat")
def chat(req: ChatRequest, principal: str = Depends(require_principal)) -> dict:
    """Start a turn. The server mints the thread id and binds it to the caller.

    A parked turn returns only ``{status: pending_approval, thread_id, reason}`` —
    poll GET /threads/{id} for the answer once a reviewer approves.
    """
    from .rag import graph

    thread_id = f"t-{uuid.uuid4().hex}"
    return graph.answer(req.message, thread_id, actor=principal)


def _own_or_404(thread_id: str, principal: str) -> None:
    from . import threads

    if not threads.is_owner(thread_id, principal):
        # 404 (not 403) so a non-owner can't confirm a thread id exists.
        raise HTTPException(status_code=404, detail="thread not found")


@app.get("/threads/{thread_id}")
def thread_status(thread_id: str, principal: str = Depends(require_principal)) -> dict:
    """Owner-only status/result. Returns the answer once the turn is resolved."""
    from .rag import graph

    _own_or_404(thread_id, principal)
    st = graph.status(thread_id)
    if st is None:
        raise HTTPException(status_code=404, detail="thread not found")
    return st


@app.get("/threads/{thread_id}/pending")
def thread_pending(thread_id: str, principal: str = Depends(require_principal)) -> dict:
    """Reviewer-only view of a parked turn — the question + answer to judge."""
    from .rag import graph

    if not is_approver(principal):
        raise HTTPException(status_code=403, detail="not an authorized reviewer")
    review = graph.review_material(thread_id)
    if review is None:
        raise HTTPException(status_code=404, detail="no turn awaiting review")
    return {"thread_id": thread_id, **review}


def _decide(thread_id: str, approved: bool, principal: str) -> dict:
    from . import threads
    from .rag import graph

    if not is_approver(principal):
        raise HTTPException(status_code=403, detail="not an authorized reviewer")
    if not threads.exists(thread_id):
        raise HTTPException(status_code=404, detail="thread not found")
    if threads.is_owner(thread_id, principal):
        raise HTTPException(status_code=403, detail="a requester cannot approve their own turn")
    decision = "approved" if approved else "rejected"
    if not threads.try_decide(thread_id, decision):
        # Already decided by a concurrent/earlier call — idempotent.
        return {"status": "already_decided", "thread_id": thread_id,
                "decision": threads.decision(thread_id)}
    return graph.resume(thread_id, approved=approved, approver=principal)


@app.post("/threads/{thread_id}/approve")
def approve(thread_id: str, principal: str = Depends(require_principal)) -> dict:
    """Release a parked answer. Reviewer-only; never the requester; atomic."""
    return _decide(thread_id, True, principal)


@app.post("/threads/{thread_id}/reject")
def reject(thread_id: str, principal: str = Depends(require_principal)) -> dict:
    """Withhold a parked answer. Reviewer-only; never the requester; atomic."""
    return _decide(thread_id, False, principal)


@app.get("/threads/{thread_id}/audit")
def thread_audit(thread_id: str, principal: str = Depends(require_principal)) -> dict:
    """The turn's decision trail — owner or an authorized reviewer only."""
    from . import threads
    from .rag import audit

    if not (threads.is_owner(thread_id, principal) or is_approver(principal)):
        raise HTTPException(status_code=404, detail="thread not found")
    return {"thread_id": thread_id, "events": audit.for_thread(thread_id)}

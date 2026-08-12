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

from fastapi import FastAPI
from pydantic import BaseModel, Field

from . import smoke
from .config import settings

log = logging.getLogger("app")


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    # Best-effort migrations so the app is self-bootstrapping; never block startup
    # on the DB (keeps /health up even if Postgres is briefly unreachable).
    try:
        from .rag import graph, store

        store.init_schema()
        graph.setup_checkpointer()
        log.info("migrations applied (schema + checkpointer)")
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


@app.post("/chat")
def chat(req: ChatRequest) -> dict:
    from .rag import graph

    thread_id = req.thread_id or f"t-{uuid.uuid4().hex}"
    result = graph.answer(req.message, thread_id)
    return {"thread_id": thread_id, **result}

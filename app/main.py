"""FastAPI entrypoint.

M0 ships liveness/readiness and a placeholder for the authenticated vertical
"smoke slice" (MI-auth'd chat + embedding + Content Safety + Postgres/pgvector +
a checkpoint migration) that proves the whole chain works after `azd up`.
The RAG `/chat` flow arrives in M1.
"""

from __future__ import annotations

from fastapi import FastAPI

from . import smoke
from .config import settings

app = FastAPI(title="azure-governed-rag", version="0.1.0")
app.include_router(smoke.router)


@app.get("/health")
def health() -> dict:
    """Liveness: the process is up. No dependency calls."""
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict:
    """Readiness: are the dependencies configured?

    M0 reports configuration presence; M1 upgrades this to real dependency
    checks (Postgres SELECT, model reachability) with bounded timeouts.
    """
    configured = {
        "azure_openai": bool(settings.azure_openai_endpoint),
        "content_safety": bool(settings.content_safety_endpoint),
        "language": bool(settings.language_endpoint),
        "postgres": bool(settings.postgres_host),
    }
    return {"ready": all(configured.values()), "configured": configured}


@app.get("/")
def root() -> dict:
    return {
        "name": "azure-governed-rag",
        "status": "M0 scaffold — infra + vertical smoke slice",
        "docs": "/docs",
    }

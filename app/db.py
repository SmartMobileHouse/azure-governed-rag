"""PostgreSQL access — keyless on Azure, password locally.

On Azure: the "password" is a short-lived Entra access token (cached, refreshed
before expiry) and the user is the managed identity's role. Locally (docker-
compose): POSTGRES_PASSWORD is set, so we use it directly. Same code path.
"""

from __future__ import annotations

import time

import psycopg
from azure.identity import DefaultAzureCredential

from .config import settings

_PG_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"
_credential: DefaultAzureCredential | None = None
_token: dict = {"value": None, "exp": 0.0}


def _entra_password() -> str:
    global _credential
    if _credential is None:
        _credential = DefaultAzureCredential()
    now = time.time()
    if not _token["value"] or now > _token["exp"] - 300:
        tok = _credential.get_token(_PG_SCOPE)
        _token["value"] = tok.token
        _token["exp"] = float(tok.expires_on)
    return _token["value"]


def _password() -> str:
    # Local dev uses a static password; Azure uses a fresh Entra token.
    return settings.postgres_password or _entra_password()


def connect() -> psycopg.Connection:
    """Open a short-lived connection. Short-lived keeps the Entra token current
    without a token-refreshing pool (a documented M1 optimization)."""
    return psycopg.connect(
        host=settings.postgres_host,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=_password(),
        sslmode=settings.postgres_sslmode,
        connect_timeout=10,
        autocommit=True,
    )


def conn_string() -> str:
    """libpq connection string (used by the LangGraph Postgres checkpointer)."""
    return (
        f"host={settings.postgres_host} dbname={settings.postgres_db} "
        f"user={settings.postgres_user} password={_password()} "
        f"sslmode={settings.postgres_sslmode}"
    )

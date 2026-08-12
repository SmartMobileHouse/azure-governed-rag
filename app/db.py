"""Keyless PostgreSQL access via Entra tokens.

Azure Postgres Entra tokens expire (~60 min), so the "password" is a cached
access token refreshed before expiry. The username is the managed identity's
role (created by the postprovision hook via `pgaadauth_create_principal`).
"""

from __future__ import annotations

import time

import psycopg
from azure.identity import DefaultAzureCredential

from .config import settings

_PG_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"
_credential = DefaultAzureCredential()
_token: dict = {"value": None, "exp": 0.0}


def _password() -> str:
    now = time.time()
    if not _token["value"] or now > _token["exp"] - 300:
        tok = _credential.get_token(_PG_SCOPE)
        _token["value"] = tok.token
        _token["exp"] = float(tok.expires_on)
    return _token["value"]


def connect() -> psycopg.Connection:
    return psycopg.connect(
        host=settings.postgres_host,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=_password(),
        sslmode=settings.postgres_sslmode,
        connect_timeout=10,
    )

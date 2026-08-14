"""Request authentication + reviewer authorization.

Easy Auth (Entra) fronts the app in Azure and injects the caller's identity as
``X-MS-CLIENT-PRINCIPAL-NAME``. This module enforces that in the application too,
so a request that reaches the app WITHOUT a validated principal (e.g. if Easy
Auth is misconfigured or the ingress is briefly exposed before the post-provision
hook runs) is rejected rather than silently treated as a local user.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from .config import settings


def require_principal(request: Request) -> str:
    """FastAPI dependency: the authenticated caller, or 401.

    ``AUTH_DISABLED=true`` (local dev only) bypasses the check with a fixed
    principal — it MUST be false anywhere deployed.
    """
    name = request.headers.get("x-ms-client-principal-name")
    if name:
        return name
    if settings.auth_disabled:
        return "local-dev"
    raise HTTPException(status_code=401, detail="authentication required")


def is_approver(principal: str) -> bool:
    """Whether a principal may approve/reject. An EMPTY allowlist authorizes
    NO ONE (fail-closed) — reviewers must be configured explicitly."""
    allow = [e.strip().lower() for e in settings.hitl_approver_emails.split(",") if e.strip()]
    return bool(allow) and principal.lower() in allow

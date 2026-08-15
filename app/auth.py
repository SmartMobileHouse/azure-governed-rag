"""Request authentication + reviewer authorization.

**Trust model (read this).** Entra **Easy Auth** on the Container App ingress is
the authentication boundary: it validates the caller's token and injects the
identity as ``X-MS-CLIENT-PRINCIPAL-NAME``, and — while it is enabled — Container
Apps strips any client-supplied ``X-MS-*`` headers, so that value is trustworthy.

This module does NOT independently validate the Entra JWT, so it does not defend
against Easy Auth being *absent* (a forged header would then be trusted). It
requires the header's presence and rejects requests without it (defence in
depth), and canonicalizes the identity so ownership and approver checks are
consistent. In-app JWT validation (issuer/audience/signature via JWKS) is the
documented hardening path — see ADR 0001.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from .config import settings


def _canonical(name: str) -> str:
    """One canonicalization policy for identity, used everywhere it's hashed or
    compared (case-insensitive), so `Alice@x` and `alice@x` never diverge."""
    return name.strip().lower()


def require_principal(request: Request) -> str:
    """FastAPI dependency: the authenticated caller (canonicalized), or 401.

    ``AUTH_DISABLED=true`` (local dev only) bypasses the check — it MUST be false
    anywhere deployed.
    """
    name = request.headers.get("x-ms-client-principal-name")
    if name:
        return _canonical(name)
    if settings.auth_disabled:
        return "local-dev"
    raise HTTPException(status_code=401, detail="authentication required")


def is_approver(principal: str) -> bool:
    """Whether a principal may approve/reject. An EMPTY allowlist authorizes
    NO ONE (fail-closed) — reviewers must be configured explicitly."""
    allow = [_canonical(e) for e in settings.hitl_approver_emails.split(",") if e.strip()]
    return bool(allow) and _canonical(principal) in allow

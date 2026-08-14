"""Pseudonymous hashing for the audit trail and thread ownership.

Uses HMAC-SHA256 keyed by ``AUDIT_HASH_KEY`` when set (recommended: a Key Vault
secret injected as an env var), so pseudonyms cannot be reversed by dictionary-
hashing a directory. Falls back to plain SHA-256 with a one-time startup warning
when no key is configured (dev only). Domain separation keeps the actor,
approver, thread and content hash-spaces distinct.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from .config import settings

log = logging.getLogger("app.hashing")
_warned = False


def _key() -> bytes | None:
    global _warned
    if not settings.audit_hash_key:
        if not _warned:
            log.warning(
                "AUDIT_HASH_KEY unset — pseudonyms use unsalted SHA-256; "
                "set a key (Key Vault secret) for production."
            )
            _warned = True
        return None
    return settings.audit_hash_key.encode("utf-8")


def _digest(domain: str, value: str) -> str:
    msg = f"{domain}\x00{value}".encode()
    key = _key()
    if key:
        return hmac.new(key, msg, hashlib.sha256).hexdigest()
    return hashlib.sha256(msg).hexdigest()


def pseudonym(value: str | None, domain: str) -> str | None:
    """A stable, non-reversible id for an actor/approver/thread within a domain."""
    if not value:
        return None
    return _digest(domain, value)


def content_hash(text: str | None) -> str | None:
    """Full-length hash of content (question/answer) — correlation, not identity."""
    if not text:
        return None
    return _digest("content", text)

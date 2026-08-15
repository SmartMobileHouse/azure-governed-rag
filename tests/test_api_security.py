"""Security-property tests for the HITL/auth redesign (no Azure/DB needed)."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth
from app.config import settings
from app.main import app
from app.rag import graph


class _Req:
    def __init__(self, headers=None):
        self.headers = headers or {}


def test_require_principal_rejects_unauthenticated(monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    with pytest.raises(HTTPException) as e:
        auth.require_principal(_Req())
    assert e.value.status_code == 401


def test_require_principal_reads_easy_auth_header(monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    assert auth.require_principal(_Req({"x-ms-client-principal-name": "alice@corp.com"})) == "alice@corp.com"


def test_require_principal_local_dev_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", True)
    assert auth.require_principal(_Req()) == "local-dev"


def test_empty_allowlist_authorizes_nobody(monkeypatch):
    monkeypatch.setattr(settings, "hitl_approver_emails", "")
    assert auth.is_approver("anyone@corp.com") is False


def test_allowlisted_reviewer_only(monkeypatch):
    monkeypatch.setattr(settings, "hitl_approver_emails", "boss@corp.com")
    assert auth.is_approver("boss@corp.com") is True
    assert auth.is_approver("alice@corp.com") is False


def test_identity_is_canonicalized(monkeypatch):
    # Mixed case must not diverge between ownership hashing and the allowlist,
    # or a requester recorded as "Alice@" could dodge the self-approval check.
    monkeypatch.setattr(settings, "auth_disabled", False)
    assert auth.require_principal(_Req({"x-ms-client-principal-name": "Alice@Corp.com "})) == "alice@corp.com"
    monkeypatch.setattr(settings, "hitl_approver_emails", "Boss@Corp.com")
    assert auth.is_approver("boss@corp.com") is True
    assert auth.is_approver("BOSS@CORP.COM") is True


def test_pending_response_hides_the_answer():
    it = SimpleNamespace(value={"reason": "sensitive terms matched (1)"})
    shaped = graph._shape(
        {"__interrupt__": [it], "answer": "SECRET ANSWER", "question": "q",
         "contexts": [{"doc_id": "d", "ordinal": 0}]},
        "t-1",
    )
    assert shaped == {"status": "pending_approval", "thread_id": "t-1",
                      "reason": "sensitive terms matched (1)"}
    assert "SECRET" not in str(shaped)


def test_chat_requires_authentication(monkeypatch):
    monkeypatch.setattr(settings, "auth_disabled", False)
    r = TestClient(app).post("/chat", json={"message": "hello"})
    assert r.status_code == 401


def test_approve_requires_a_configured_reviewer(monkeypatch):
    # Auth disabled → caller is "local-dev"; empty allowlist → nobody may approve.
    monkeypatch.setattr(settings, "auth_disabled", True)
    monkeypatch.setattr(settings, "hitl_approver_emails", "")
    r = TestClient(app).post("/threads/t-x/approve")
    assert r.status_code == 403

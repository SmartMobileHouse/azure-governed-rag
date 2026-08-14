"""Audit privacy tests — canaries must never survive into persisted fields."""

from app import hashing
from app.rag import audit


def test_governance_allowlist_drops_free_text_and_raw_ids():
    gov = {
        "input_shield": {"ok": True, "attack": False, "error": "SECRET_ERR"},
        "chunk_shield": {"ok": True, "quarantined": ["John-Smith-HIV:0", "evil:1"]},
        "groundedness": {"ok": True, "grounded": False,
                         "reason": "answer states SSN 123-45-6789 unsupported", "error": "OPENAI_BODY"},
        "pii": {"ok": True, "count": 2, "categories": {"Email": 1, "Person": 1}, "error": None},
        "approval": {"required": True, "approved": True, "approver": "boss@corp.com",
                     "reason": "low groundedness; sensitive terms matched (1)"},
    }
    safe = audit._safe_governance(gov)
    blob = str(safe)
    for canary in ("SECRET_ERR", "OPENAI_BODY", "SSN", "123-45-6789", "John-Smith-HIV", "boss@corp.com"):
        assert canary not in blob, canary

    assert safe["chunk_shield"]["quarantined_count"] == 2
    assert safe["groundedness"] == {"ok": True, "grounded": False}
    assert safe["pii"]["categories"] == {"Email": 1, "Person": 1}  # entity types are safe
    assert safe["approval"]["approved"] is True
    assert "low_groundedness" in safe["approval"]["reason_codes"]
    assert "sensitive_terms" in safe["approval"]["reason_codes"]
    assert safe["approval"]["approver_hash"]  # hashed, not the raw email
    assert "approver" not in safe["approval"]


def test_hashes_are_full_length_and_domain_separated():
    h = hashing.content_hash("hello world")
    assert h is not None and len(h) == 64
    actor = hashing.pseudonym("boss@corp.com", "actor")
    approver = hashing.pseudonym("boss@corp.com", "approver")
    assert actor != approver  # domain separation
    assert hashing.pseudonym(None, "actor") is None

"""Unit tests for safety primitives that the eval stubs bypass."""

from app.rag import safety


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_shield_partial_document_response_is_not_ok(monkeypatch):
    # 2 documents submitted, only 1 analysis returned → must fail the check.
    monkeypatch.setattr(safety, "cognitive_token", lambda: "tok")
    monkeypatch.setattr(
        safety.httpx, "post",
        lambda *a, **k: _FakeResp(
            {"userPromptAnalysis": {"attackDetected": False},
             "documentsAnalysis": [{"attackDetected": False}]}
        ),
    )
    res = safety.shield_prompt("q", ["chunk-a", "chunk-b"])
    assert res["ok"] is False
    assert res["error"] == "IncompleteShieldResponse"


def test_shield_complete_response_ok(monkeypatch):
    monkeypatch.setattr(safety, "cognitive_token", lambda: "tok")
    monkeypatch.setattr(
        safety.httpx, "post",
        lambda *a, **k: _FakeResp(
            {"userPromptAnalysis": {"attackDetected": True},
             "documentsAnalysis": [{"attackDetected": False}, {"attackDetected": True}]}
        ),
    )
    res = safety.shield_prompt("q", ["chunk-a", "chunk-b"])
    assert res["ok"] is True
    assert res["user_attack"] is True
    assert res["document_attacks"] == [False, True]


def test_split_long_text():
    assert safety._split("abc", 5000) == ["abc"]
    parts = safety._split("x" * 12000, 5000)
    assert [len(p) for p in parts] == [5000, 5000, 2000]

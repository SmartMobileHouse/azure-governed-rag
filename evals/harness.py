"""Deterministic governance eval harness (M4).

Runs the REAL LangGraph pipeline with every Azure leaf call stubbed per case, so
the governance *behaviour* — block / quarantine / redact / gate / approve /
reject — is exercised and gated in CI with zero cloud dependency.

This intentionally does NOT evaluate model quality (does the model stay grounded,
do Prompt Shields catch a novel attack). That is non-deterministic, needs Azure,
and runs separately in ``evals/live_eval.py`` — it is not a PR gate.
"""

from __future__ import annotations

import json
import os

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.config import settings
from app.rag import graph, llm, safety, store

_DATASET = os.path.join(os.path.dirname(__file__), "dataset.jsonl")


def load_cases(path: str = _DATASET) -> list[dict]:
    cases: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                cases.append(json.loads(line))
    return cases


def _install_stubs(monkeypatch, case: dict) -> None:
    """Replace the Azure-touching leaves with canned per-case responses."""
    stub = case.get("stub", {})
    monkeypatch.setattr(llm, "embed_one", lambda q: [0.0] * 1536)
    monkeypatch.setattr(
        store, "similarity_search", lambda vec, k=4: [dict(c) for c in stub.get("chunks", [])]
    )

    def _shield(user_prompt, documents):
        # guard_input calls with no documents; shield_chunks calls with the chunks.
        if not documents:
            return {
                "ok": True,
                "user_attack": stub.get("shield_user_attack", False),
                "document_attacks": [],
                "error": None,
            }
        return {
            "ok": True,
            "user_attack": False,
            "document_attacks": stub.get("shield_doc_attacks", [False] * len(documents)),
            "error": None,
        }

    monkeypatch.setattr(safety, "shield_prompt", _shield)
    monkeypatch.setattr(llm, "generate", lambda q, ctx: stub.get("answer", ""))
    monkeypatch.setattr(
        safety,
        "check_groundedness",
        lambda answer, ctx: {
            "ok": True,
            "grounded": stub.get("grounded", True),
            "reason": "",
            "error": None,
        },
    )
    cats = stub.get("pii_categories", {})
    monkeypatch.setattr(
        safety,
        "detect_pii",
        lambda text: {
            "ok": True,
            "redacted": stub.get("pii_redacted", text),
            "categories": cats,
            "count": sum(cats.values()),
            "error": None,
        },
    )


def run_case(monkeypatch, case: dict) -> dict:
    """Run one case through the graph and return the shaped API response.

    If the case sets ``resume`` and the turn parked, it resumes with that
    approve/reject decision so approval-gate outcomes can be asserted too.
    """
    for key, value in case.get("config", {}).items():
        monkeypatch.setattr(settings, key, value)
    _install_stubs(monkeypatch, case)

    compiled = graph._builder().compile(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": f"eval-{case['id']}"}}
    result = compiled.invoke({"question": case["question"]}, cfg)
    shaped = graph._shape(result, cfg["configurable"]["thread_id"])

    if "resume" in case and shaped.get("status") == "pending_approval":
        result = compiled.invoke(
            Command(resume={"approved": case["resume"], "approver": "eval@ci"}), cfg
        )
        shaped = graph._shape(result, cfg["configurable"]["thread_id"])
    return shaped

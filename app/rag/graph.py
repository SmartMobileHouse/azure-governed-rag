"""The governed RAG graph (LangGraph).

    START → guard_input → retrieve → shield_chunks → generate → groundedness → END
              │ (blocked)
              └────────────────────────────────────────────────────────────→ END

M1 was retrieve → generate. M2 adds the safety layer as ordinary graph nodes:

* **guard_input** — Prompt Shields on the user prompt; a detected injection (or a
  failed check under fail-closed) short-circuits to END with a refusal.
* **shield_chunks** — Prompt Shields on retrieved chunks; flagged chunks are
  quarantined (excluded from generation) to defend against indirect injection.
* **groundedness** — an LLM self-check on the answer; an unsupported answer is
  replaced with a safe fallback.

Every check records its verdict under state["governance"], surfaced in the
/chat response. State is persisted per thread_id by the Postgres checkpointer,
which is where the M3 human-in-the-loop `interrupt` will slot in.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph

from .. import db
from ..config import settings
from . import llm, safety, store

_REFUSAL = (
    "This request was blocked by the safety layer — it looks like a prompt-injection "
    "or policy-violating input."
)
_UNGROUNDED_FALLBACK = (
    "I couldn't produce an answer fully supported by the available sources, so I'm "
    "declining to answer rather than speculate."
)


class RagState(TypedDict, total=False):
    question: str
    contexts: list[dict[str, Any]]
    answer: str
    blocked: bool
    block_reason: str
    grounded: bool
    governance: dict[str, Any]


def _guard_input(state: RagState) -> dict:
    """Prompt Shields on the user prompt; block early on a detected injection."""
    if not settings.safety_enabled:
        return {"blocked": False, "governance": {"input_shield": {"status": "disabled"}}}
    res = safety.shield_prompt(state["question"], [])
    gov = {"input_shield": {"ok": res["ok"], "attack": res["user_attack"], "error": res["error"]}}
    if res["user_attack"] or (not res["ok"] and settings.safety_fail_closed):
        reason = (
            "prompt-injection detected in the request"
            if res["user_attack"]
            else "input safety check unavailable (fail-closed)"
        )
        return {"blocked": True, "block_reason": reason, "answer": _REFUSAL, "governance": gov}
    return {"blocked": False, "governance": gov}


def _route_after_input(state: RagState) -> str:
    return "blocked" if state.get("blocked") else "retrieve"


def _retrieve(state: RagState) -> dict:
    embedding = llm.embed_one(state["question"])
    return {"contexts": store.similarity_search(embedding, k=settings.retrieval_top_k)}


def _shield_chunks(state: RagState) -> dict:
    """Prompt Shields on retrieved chunks; quarantine flagged ones (indirect injection)."""
    ctxs = state.get("contexts", [])
    gov = dict(state.get("governance", {}))
    if not settings.safety_enabled or not ctxs:
        gov["chunk_shield"] = {"status": "disabled" if not settings.safety_enabled else "no-chunks"}
        return {"governance": gov}
    res = safety.shield_prompt(state["question"], [c["content"] for c in ctxs])
    attacks = res["document_attacks"]
    kept, quarantined = [], []
    for i, c in enumerate(ctxs):
        flagged = attacks[i] if i < len(attacks) else False
        if flagged or (not res["ok"] and settings.safety_fail_closed):
            quarantined.append(f"{c['doc_id']}:{c['ordinal']}")
        else:
            kept.append(c)
    gov["chunk_shield"] = {"ok": res["ok"], "quarantined": quarantined, "error": res["error"]}
    return {"contexts": kept, "governance": gov}


def _generate(state: RagState) -> dict:
    return {"answer": llm.generate(state["question"], state.get("contexts", []))}


def _check_groundedness(state: RagState) -> dict:
    """LLM self-check; replace an unsupported answer with a safe fallback."""
    gov = dict(state.get("governance", {}))
    if not (settings.safety_enabled and settings.groundedness_enabled):
        gov["groundedness"] = {"status": "disabled"}
        return {"grounded": True, "governance": gov}
    ctxs = state.get("contexts", [])
    context_block = "\n\n".join(f"[{c['doc_id']}:{c['ordinal']}] {c['content']}" for c in ctxs)
    res = safety.check_groundedness(state.get("answer", ""), context_block)
    gov["groundedness"] = {
        "ok": res["ok"],
        "grounded": res["grounded"],
        "reason": res["reason"],
        "error": res["error"],
    }
    out: dict = {"grounded": res["grounded"], "governance": gov}
    if not res["grounded"] and (res["ok"] or settings.safety_fail_closed):
        out["answer"] = _UNGROUNDED_FALLBACK
    return out


def _builder() -> StateGraph:
    g = StateGraph(RagState)
    g.add_node("guard_input", _guard_input)
    g.add_node("retrieve", _retrieve)
    g.add_node("shield_chunks", _shield_chunks)
    g.add_node("generate", _generate)
    g.add_node("groundedness", _check_groundedness)
    g.add_edge(START, "guard_input")
    g.add_conditional_edges(
        "guard_input", _route_after_input, {"blocked": END, "retrieve": "retrieve"}
    )
    g.add_edge("retrieve", "shield_chunks")
    g.add_edge("shield_chunks", "generate")
    g.add_edge("generate", "groundedness")
    g.add_edge("groundedness", END)
    return g


def setup_checkpointer() -> None:
    """Create the LangGraph checkpoint tables (idempotent). Run once at migrate."""
    with PostgresSaver.from_conn_string(db.conn_string()) as cp:
        cp.setup()


def answer(question: str, thread_id: str) -> dict:
    """Run the graph for one turn, persisting state under thread_id."""
    with PostgresSaver.from_conn_string(db.conn_string()) as cp:
        graph = _builder().compile(checkpointer=cp)
        result = graph.invoke(
            {"question": question},
            config={"configurable": {"thread_id": thread_id}},
        )
    contexts = result.get("contexts", [])
    return {
        "answer": result.get("answer", ""),
        "sources": [f"{c['doc_id']}:{c['ordinal']}" for c in contexts],
        "blocked": bool(result.get("blocked", False)),
        "grounded": bool(result.get("grounded", True)),
        "governance": result.get("governance", {}),
    }

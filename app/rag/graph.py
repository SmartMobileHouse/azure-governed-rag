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
from langgraph.types import Command, interrupt

from .. import db, threads
from ..config import settings
from . import audit, llm, safety, store

_REFUSAL = (
    "This request was blocked by the safety layer — it looks like a prompt-injection "
    "or policy-violating input."
)
_UNGROUNDED_FALLBACK = (
    "I couldn't produce an answer fully supported by the available sources, so I'm "
    "declining to answer rather than speculate."
)
_REJECTED_MESSAGE = (
    "This answer was withheld by a human reviewer and not released."
)
_PII_WITHHELD = (
    "This answer was withheld because personal-data screening could not run."
)


class RagState(TypedDict, total=False):
    question: str
    contexts: list[dict[str, Any]]
    answer: str
    blocked: bool
    block_reason: str
    grounded: bool
    pii_found: bool
    approved: bool
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
    """LLM self-check.

    Without HITL this replaces an unsupported answer with a safe fallback (M2
    behaviour). With HITL enabled it records the verdict but leaves the answer
    intact — the approval gate hands that decision to a human.
    """
    gov = dict(state.get("governance", {}))
    grounded = True
    if settings.safety_enabled and settings.groundedness_enabled:
        ctxs = state.get("contexts", [])
        context_block = "\n\n".join(f"[{c['doc_id']}:{c['ordinal']}] {c['content']}" for c in ctxs)
        res = safety.check_groundedness(state.get("answer", ""), context_block)
        # Fail CLOSED when the check itself errored: treat as ungrounded so the
        # answer is withheld (no HITL) or parked (HITL) instead of released.
        grounded = res["grounded"] if res["ok"] else (not settings.safety_fail_closed)
        gov["groundedness"] = {
            "ok": res["ok"],
            "grounded": grounded,
            "reason": res["reason"],
            "error": res["error"],
        }
    else:
        gov["groundedness"] = {"status": "disabled"}

    out: dict = {"grounded": grounded, "governance": gov}
    check = gov["groundedness"]
    if not settings.hitl_enabled and not grounded and (check.get("ok") or settings.safety_fail_closed):
        out["answer"] = _UNGROUNDED_FALLBACK
    return out


def _redact_pii(state: RagState) -> dict:
    """Mask PII in the answer via Azure AI Language; record types + counts only.

    Runs regardless of HITL. Records entity *categories* and counts (never the
    raw values). On a failed check: fail-open returns the answer as-is (flagged);
    fail-closed withholds it.
    """
    gov = dict(state.get("governance", {}))
    answer = state.get("answer", "")
    if not settings.pii_enabled or not answer:
        gov["pii"] = {"status": "disabled" if not settings.pii_enabled else "no-answer"}
        return {"governance": gov}
    res = safety.detect_pii(answer)
    gov["pii"] = {
        "ok": res["ok"],
        "categories": res["categories"],
        "count": res["count"],
        "error": res["error"],
    }
    out: dict = {"governance": gov}
    if res["ok"]:
        if res["count"] > 0:
            out["answer"] = res["redacted"]  # mask the PII in the returned answer
            out["pii_found"] = True
    else:
        # The PII check failed. Flag it so HITL_ON_PII can still route the turn,
        # and fail CLOSED by default — withhold rather than return unredacted text.
        out["pii_found"] = True
        if settings.pii_fail_closed:
            out["answer"] = _PII_WITHHELD
    return out


def _needs_approval(state: RagState) -> tuple[bool, str]:
    """Decide whether a turn requires human sign-off, and why. Pure — safe to
    call before ``interrupt`` (which re-executes the node head on resume)."""
    reasons: list[str] = []
    if not state.get("grounded", True):
        reasons.append("low groundedness")
    if settings.hitl_on_pii and state.get("pii_found"):
        reasons.append("PII detected in answer")
    terms = [t.strip().lower() for t in settings.hitl_sensitive_terms.split(",") if t.strip()]
    haystack = f"{state.get('question', '')} {state.get('answer', '')}".lower()
    hits = [t for t in terms if t in haystack]
    if hits:
        reasons.append("sensitive terms: " + ", ".join(hits))
    return bool(reasons), "; ".join(reasons)


def _route_after_checks(state: RagState) -> str:
    if not settings.hitl_enabled:
        return "end"
    needs, _ = _needs_approval(state)
    return "approval_gate" if needs else "end"


def _approval_gate(state: RagState) -> dict:
    """Pause for human approval. ``interrupt`` is the FIRST side-effecting call,
    so nothing before it re-runs on resume."""
    _, reason = _needs_approval(state)
    # Only the reason is surfaced to the requester (via _shape). The question,
    # answer and sources stay in the checkpoint and are shown ONLY to an
    # authorized reviewer via graph.review_material / the /pending endpoint.
    decision = interrupt({"reason": reason})
    approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
    approver = decision.get("approver") if isinstance(decision, dict) else None
    gov = dict(state.get("governance", {}))
    gov["approval"] = {
        "required": True,
        "reason": reason,
        "approved": approved,
        "approver": approver,
    }
    out: dict = {"approved": approved, "governance": gov}
    if not approved:
        out["answer"] = _REJECTED_MESSAGE
    return out


def _builder() -> StateGraph:
    g = StateGraph(RagState)
    g.add_node("guard_input", _guard_input)
    g.add_node("retrieve", _retrieve)
    g.add_node("shield_chunks", _shield_chunks)
    g.add_node("generate", _generate)
    g.add_node("groundedness", _check_groundedness)
    g.add_node("pii", _redact_pii)
    g.add_node("approval_gate", _approval_gate)
    g.add_edge(START, "guard_input")
    g.add_conditional_edges(
        "guard_input", _route_after_input, {"blocked": END, "retrieve": "retrieve"}
    )
    g.add_edge("retrieve", "shield_chunks")
    g.add_edge("shield_chunks", "generate")
    g.add_edge("generate", "groundedness")
    g.add_edge("groundedness", "pii")
    g.add_conditional_edges(
        "pii", _route_after_checks, {"approval_gate": "approval_gate", "end": END}
    )
    g.add_edge("approval_gate", END)
    return g


def setup_checkpointer() -> None:
    """Create the LangGraph checkpoint tables (idempotent). Run once at migrate."""
    with PostgresSaver.from_conn_string(db.conn_string()) as cp:
        cp.setup()


def _sources(state: dict) -> list[str]:
    return [f"{c['doc_id']}:{c['ordinal']}" for c in state.get("contexts", [])]


def _shape(result: dict, thread_id: str) -> dict:
    """Map a graph result to the REQUESTER-facing response.

    A parked turn returns only the reason — never the question, answer or sources.
    Those live in the checkpoint and are shown solely to an authorized reviewer.
    """
    if result.get("__interrupt__"):
        reason = result["__interrupt__"][0].value.get("reason", "")
        return {"status": "pending_approval", "thread_id": thread_id, "reason": reason}
    return {
        "status": "complete",
        "thread_id": thread_id,
        "answer": result.get("answer", ""),
        "sources": _sources(result),
        "blocked": bool(result.get("blocked", False)),
        "grounded": bool(result.get("grounded", True)),
        "approved": result.get("approved"),
        "governance": result.get("governance", {}),
    }


def _audit(result: dict, thread_id: str, actor: str | None, checkpoint_id: str | None) -> None:
    """Record one privacy-safe audit event for the transition just made."""
    if result.get("__interrupt__"):
        decision = "pending"
    else:
        approved = result.get("approved")
        decision = (
            "blocked" if result.get("blocked")
            else "approved" if approved is True
            else "rejected" if approved is False
            else "answered"
        )
    audit.record(
        thread_id=thread_id, decision=decision, actor=actor,
        question=result.get("question"), answer=result.get("answer"),
        sources=_sources(result), governance=result.get("governance"),
        checkpoint_id=checkpoint_id,
    )


def _checkpoint_id(graph, cfg: dict) -> str | None:
    return graph.get_state(cfg).config.get("configurable", {}).get("checkpoint_id")


def answer(question: str, thread_id: str, actor: str | None = None) -> dict:
    """Run the graph for one turn, persisting state under thread_id.

    Records thread ownership (so only the caller can later read status/audit) and
    returns a ``complete`` response, or ``pending_approval`` (reason only) if the
    turn parked at the human approval gate.
    """
    threads.create(thread_id, actor)
    cfg = {"configurable": {"thread_id": thread_id}}
    with PostgresSaver.from_conn_string(db.conn_string()) as cp:
        graph = _builder().compile(checkpointer=cp)
        result = graph.invoke({"question": question}, config=cfg)
        checkpoint_id = _checkpoint_id(graph, cfg)
    _audit(result, thread_id, actor, checkpoint_id)
    return _shape(result, thread_id)


def review_material(thread_id: str) -> dict | None:
    """Reviewer-only view of a PARKED turn: the question, answer and sources to
    judge. Returns None if the thread isn't currently awaiting approval."""
    cfg = {"configurable": {"thread_id": thread_id}}
    with PostgresSaver.from_conn_string(db.conn_string()) as cp:
        graph = _builder().compile(checkpointer=cp)
        snap = graph.get_state(cfg)
    if not snap.values or not snap.next:
        return None
    values = snap.values
    return {
        "reason": _needs_approval(values)[1],
        "question": values.get("question", ""),
        "answer": values.get("answer", ""),
        "sources": _sources(values),
    }


def status(thread_id: str) -> dict | None:
    """Owner-facing status/result. Returns the answer only once the turn is
    resolved (auto-completed or approved); a rejected turn returns the withheld
    message. None if the thread has no state."""
    cfg = {"configurable": {"thread_id": thread_id}}
    with PostgresSaver.from_conn_string(db.conn_string()) as cp:
        graph = _builder().compile(checkpointer=cp)
        snap = graph.get_state(cfg)
    if not snap.values:
        return None
    if snap.next:
        return {"status": "pending_approval", "thread_id": thread_id,
                "reason": _needs_approval(snap.values)[1]}
    return _shape(snap.values, thread_id)


def resume(thread_id: str, approved: bool, approver: str | None) -> dict:
    """Resume a parked turn with a human decision, then audit it. Callers gate
    this behind an atomic decision (threads.try_decide) so it runs at most once."""
    cfg = {"configurable": {"thread_id": thread_id}}
    with PostgresSaver.from_conn_string(db.conn_string()) as cp:
        graph = _builder().compile(checkpointer=cp)
        snap = graph.get_state(cfg)
        if not snap.values:
            return {"status": "not_found", "thread_id": thread_id}
        if not snap.next:  # nothing pending → already resolved
            return _shape(snap.values, thread_id)
        result = graph.invoke(
            Command(resume={"approved": approved, "approver": approver}), cfg
        )
        checkpoint_id = _checkpoint_id(graph, cfg)
    _audit(result, thread_id, approver, checkpoint_id)
    return _shape(result, thread_id)

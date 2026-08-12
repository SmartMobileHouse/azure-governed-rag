"""The RAG graph (LangGraph).

    START → retrieve (pgvector) → generate (Azure OpenAI) → END

State is persisted per thread_id by the Postgres checkpointer (the same
Postgres that holds the vectors), which gives durable, resumable runs and is
the seam where M2 safety nodes and the M3 human-in-the-loop `interrupt` slot in.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph

from .. import db
from ..config import settings
from . import llm, store


class RagState(TypedDict, total=False):
    question: str
    contexts: list[dict[str, Any]]
    answer: str


def _retrieve(state: RagState) -> dict:
    embedding = llm.embed_one(state["question"])
    return {"contexts": store.similarity_search(embedding, k=settings.retrieval_top_k)}


def _generate(state: RagState) -> dict:
    return {"answer": llm.generate(state["question"], state.get("contexts", []))}


def _builder() -> StateGraph:
    g = StateGraph(RagState)
    g.add_node("retrieve", _retrieve)
    g.add_node("generate", _generate)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", END)
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
    }

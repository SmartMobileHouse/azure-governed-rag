"""Embeddings + chat generation via the keyless Azure OpenAI client."""

from __future__ import annotations

from ..azure_clients import openai_client
from ..config import settings

_SYSTEM = (
    "You are a precise assistant. Answer ONLY from the provided context. "
    "If the answer is not in the context, say you don't know. Cite the source "
    "ids you used in square brackets, e.g. [doc-1:2]."
)


def embed(texts: list[str]) -> list[list[float]]:
    resp = openai_client().embeddings.create(
        model=settings.azure_openai_embedding_deployment, input=texts
    )
    return [d.embedding for d in resp.data]


def embed_one(text: str) -> list[float]:
    return embed([text])[0]


def generate(question: str, contexts: list[dict]) -> str:
    if not contexts:
        return "I don't know — no relevant context was found."
    context_block = "\n\n".join(
        f"[{c['doc_id']}:{c['ordinal']}] {c['content']}" for c in contexts
    )
    resp = openai_client().chat.completions.create(
        model=settings.azure_openai_chat_deployment,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"Context:\n{context_block}\n\nQuestion: {question}"},
        ],
        max_completion_tokens=settings.chat_max_completion_tokens,
    )
    return (resp.choices[0].message.content or "").strip()

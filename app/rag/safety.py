"""M2 safety layer primitives.

Two governance checks, kept independent of the graph so they can be unit-probed
and reused:

* ``shield_prompt`` — Azure AI Content Safety **Prompt Shields**: detects direct
  (user prompt) and indirect (retrieved document) prompt-injection attacks.
  The azure-ai-contentsafety 1.0.0 SDK has no typed method for it, so we call
  the ``text:shieldPrompt`` REST operation through the client's ``send_request``
  (still keyless — same Entra credential).
* ``check_groundedness`` — an LLM self-check that judges whether the generated
  answer is supported by the retrieved context. This is the plan's portable
  fallback; the Content Safety groundedness *preview* API is a later flag.

Every function reports its own failure (``ok``) and never raises, so the graph
nodes can apply a fail-open / fail-closed policy explicitly.
"""

from __future__ import annotations

import logging

import httpx

from ..azure_clients import cognitive_token, openai_client
from ..config import settings

log = logging.getLogger("app.safety")

_SHIELD_API_VERSION = "2024-09-01"

_GROUND_SYSTEM = (
    "You are a strict grounding judge. Given CONTEXT and an ANSWER, decide whether "
    "every factual claim in the ANSWER is directly supported by the CONTEXT. "
    "An answer that says it doesn't know is grounded. Reply with exactly one line: "
    "'GROUNDED' or 'UNGROUNDED: <reason in <=15 words>'."
)


def shield_prompt(user_prompt: str, documents: list[str]) -> dict:
    """Run Prompt Shields over the user prompt and any documents (chunks).

    Returns ``{ok, user_attack, document_attacks, error}``. On failure the
    attack flags default to False (fail-open shape); callers inspect ``ok`` to
    apply a fail-closed policy.
    """
    result = {
        "ok": True,
        "user_attack": False,
        "document_attacks": [False] * len(documents),
        "error": None,
    }
    try:
        url = (
            f"{settings.content_safety_endpoint.rstrip('/')}"
            "/contentsafety/text:shieldPrompt"
        )
        resp = httpx.post(
            url,
            params={"api-version": _SHIELD_API_VERSION},
            headers={"Authorization": f"Bearer {cognitive_token()}"},
            json={"userPrompt": user_prompt, "documents": documents},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        result["user_attack"] = bool(
            data.get("userPromptAnalysis", {}).get("attackDetected", False)
        )
        result["document_attacks"] = [
            bool(d.get("attackDetected", False))
            for d in data.get("documentsAnalysis", [])
        ]
    except Exception as e:  # noqa: BLE001 - report, never raise into the graph
        log.warning("prompt shields check failed: %s", e)
        result["ok"] = False
        result["error"] = str(e)[:200]
    return result


def check_groundedness(answer: str, context_block: str) -> dict:
    """LLM self-check: is ``answer`` supported by ``context_block``?

    Returns ``{ok, grounded, reason, error}``. On failure ``grounded`` defaults
    to True (fail-open shape); callers inspect ``ok`` for fail-closed.
    """
    result = {"ok": True, "grounded": True, "reason": "", "error": None}
    try:
        r = openai_client().chat.completions.create(
            model=settings.azure_openai_chat_deployment,
            messages=[
                {"role": "system", "content": _GROUND_SYSTEM},
                {"role": "user", "content": f"CONTEXT:\n{context_block}\n\nANSWER:\n{answer}"},
            ],
            max_completion_tokens=200,
            reasoning_effort="minimal",
        )
        text = (r.choices[0].message.content or "").strip()
        result["grounded"] = not text.upper().startswith("UNGROUNDED")
        if not result["grounded"]:
            _, _, reason = text.partition(":")
            result["reason"] = reason.strip()[:200]
    except Exception as e:  # noqa: BLE001
        log.warning("groundedness check failed: %s", e)
        result["ok"] = False
        result["error"] = str(e)[:200]
    return result

"""Version stamps recorded in every audit event so a decision is reproducible.

Bump these deliberately when the thing they name changes:
* POLICY_VERSION — safety/HITL policy (thresholds, fail-open/closed, triggers).
* PROMPT_VERSION — the system/safety/groundedness prompts.
The model is stamped separately from settings (already a Bicep param).
"""

from __future__ import annotations

POLICY_VERSION = "m3-slice2"
PROMPT_VERSION = "2026-08-12"

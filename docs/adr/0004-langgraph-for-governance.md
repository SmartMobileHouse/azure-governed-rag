# 0004 — Governance as LangGraph nodes; HITL via `interrupt`

**Status:** Accepted

## Context
The governance controls (shields, groundedness, PII, human approval) could live
as ad-hoc middleware around a chat call. But a human-in-the-loop gate needs the
run to **pause, persist, and resume across requests** — and every step needs to
be inspectable for the audit trail.

## Decision
Model the whole turn as a **LangGraph `StateGraph`**, one node per stage
(`guard_input → retrieve → shield_chunks → generate → groundedness → pii →
approval_gate`). The approval gate uses LangGraph's **`interrupt`**, backed by the
**Postgres checkpointer**: a flagged turn parks its full state under the
`thread_id` and resumes when `/threads/{id}/approve|reject` is called — on any
replica. `interrupt` sits at the top of its node so nothing re-runs on resume.

## Consequences
- Pause/resume and durable, replayable state come from the framework, not custom
  plumbing; the same seam hosts future nodes (e.g., an extraction-intent check).
- Every node's output is a discrete, checkpointed state — a natural source for the
  per-turn audit record.
- Coupling to LangGraph's `interrupt`/checkpointer contract; versions are pinned.
- The checkpointer tables must be migrated at startup, and its connection uses the
  keyless token path like everything else.

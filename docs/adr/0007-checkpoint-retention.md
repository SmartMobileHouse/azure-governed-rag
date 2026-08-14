# 0007 — Checkpoint retention boundary

**Status:** Accepted (with a known limitation)

## Context
The LangGraph `PostgresSaver` checkpointer persists the full graph state per turn
— the raw question, retrieved chunks, and the pre-redaction answer — so a parked
turn can be resumed later on any replica ([ADR 0004](0004-langgraph-for-governance.md)).
The audit log is deliberately privacy-safe (hashes only), but the checkpoint
tables are not: they hold raw content in the same PostgreSQL server.

## Decision
Keep checkpoints as the operational store and **document the boundary honestly**:
the privacy-safe guarantee applies to `audit_log`, not to `checkpoints`. Raw
content lives in the checkpoint tables with **no TTL by default**.

## Consequences
- Pause/resume and replay work with no extra infrastructure.
- A database reader or backup can see raw prompts/answers/chunks. Deployments on
  sensitive data **must** add a retention/cleanup job (e.g. periodic
  `DELETE FROM checkpoints WHERE …` past a TTL) and should consider a separate,
  access-controlled store for the audit log, and encryption at rest.
- The README (`Data handling & retention`) and `governance-mapping.md` state this
  explicitly so adopters don't assume "privacy-safe audit" means "nothing raw is
  persisted." A managed retention/TTL is the tracked hardening follow-up.

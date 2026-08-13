# 0003 — One Postgres for vectors, checkpointer, and audit

**Status:** Accepted

## Context
The system needs three kinds of durable state: the **vector store** (pgvector
chunks), the **LangGraph checkpointer** (per-thread graph state that makes
pause/resume possible), and the **audit log**. Each could be a separate managed
service (e.g., a dedicated vector DB, a separate audit store).

## Decision
Run all three in a **single PostgreSQL Flexible Server**, separated by table:
`rag_chunks` (pgvector), the LangGraph `checkpoints*` tables, and `audit_log`.

## Consequences
- One cheap resource (B1ms) to provision, secure, and pay for — the biggest lever
  on the template's idle cost. Keyless auth and backup apply once.
- pgvector keeps retrieval in the same transactional store as the rest — no extra
  system to operate for a reference architecture.
- The audit log shares a server with operational state. That's acceptable for a
  template; a production deployment with strict separation-of-duties should move
  `audit_log` to its own store (called out in `governance-mapping.md`).
- Scaling limits are shared. If vector volume or QPS grows, retrieval and
  checkpointing compete for the same instance — revisit sizing or split then.

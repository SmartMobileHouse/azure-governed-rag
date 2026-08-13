# Architecture Decision Records

Short records of the load-bearing decisions in this template — the ones a
reviewer would otherwise have to reverse-engineer from the code. Each states the
context, the decision, and the trade-off we accepted.

| # | Decision |
|---|---|
| [0001](0001-keyless-identity-and-auth.md) | Keyless managed identity + Entra Easy Auth |
| [0002](0002-postgres-entra-token-auth.md) | Postgres auth via Entra token, not a Key Vault password |
| [0003](0003-one-postgres-multiple-jobs.md) | One Postgres for vectors, checkpointer, and audit |
| [0004](0004-langgraph-for-governance.md) | Governance as LangGraph nodes; HITL via `interrupt` |
| [0005](0005-non-streaming-responses.md) | Non-streaming responses |
| [0006](0006-single-region.md) | Single region (`swedencentral`) |

Format: Context · Decision · Consequences. Status is `Accepted` unless noted.

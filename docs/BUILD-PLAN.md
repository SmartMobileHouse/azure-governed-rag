# azure-governed-rag — Build Plan (rev. 2)

A ready-to-deploy, **governed RAG assistant** on Azure AI Foundry, orchestrated
with **LangGraph**. Authenticated, safety-gated, auditable, deployable with one
command (`azd up`). Doubles as an internal delivery accelerator and a public
authority artifact. MIT, public, under github.com/SmartMobileHouse.

> **rev. 2** folds in a dual-model design review (gpt-5.6-sol + fable-5). Biggest
> changes: **auth is mandatory**, the **durable-state contract moves to M1**,
> **M0 becomes a thin vertical slice** (not provision-and-hello), the **safety
> decomposition is corrected** (PII ≠ Content Safety; hard blocks are
> non-overridable), and a **risk register + cost table** are added.

## Locked decisions
- Use case: **governed RAG assistant** (single-agent / multi-agent = later)
- Orchestration: **LangGraph** (graph + Postgres checkpointer + interrupt/HITL)
- Vector store: **pgvector on Azure Database for PostgreSQL Flexible Server** —
  the *same* server also backs the LangGraph checkpointer, but in **separate
  schemas + roles + connection pools** (isolation), documented as one-server v1
  with a separate-server production path.
- Interface: **minimal chat UI + FastAPI**, **v1 is non-streaming** (stated;
  streaming interacts with the output-safety node and `interrupt`, deferred).
- Host: **Azure Container Apps** with **built-in Entra auth (Easy Auth) ON by
  default**; IaC in **Bicep**, deploy via **`azd up`**.
- Identity: **Managed Identity, keyless** for Azure OpenAI, Content Safety, and
  Language. Postgres uses **Entra auth with a token-refreshing connection
  factory** (tokens expire ~60 min); if that proves too fragile for the target
  audience, fall back to a **password in Key Vault** (documented exception).

## Non-negotiables (from the review)
- **No anonymous `/chat`.** Auth + **server-issued opaque thread IDs** + owner
  checks on every retrieval/resume. "Governed" without auth is a contradiction.
- **Hard safety violations are non-overridable.** HITL is for *low groundedness /
  sensitive-data disclosure / ambiguous authorization* — never to approve past a
  content-safety block.
- **Name each safety API.** Prompt Shields, harmful-content analysis, and
  groundedness are distinct Content Safety features; **PII is Azure AI Language**,
  not Content Safety. Groundedness is **preview, region-limited, English-only**.
- **Audit ≠ telemetry.** No raw PII into Azure Monitor; audit is a versioned,
  pseudonymized, redacted, access-controlled record, separate from ops logs.
- **Governance mapping is "supports," not "compliant"** — explicit
  non-compliance disclaimer + customer obligations (also our own content rule).

## The LangGraph graph (target)
```
authenticated request (owner-scoped thread_id)
  → prompt-shield (user input AND retrieved chunks) + PII detect (Language)
  → retrieve (pgvector)  → generate (Foundry, MI)
  → groundedness check (+ LLM self-check fallback if region-unavailable)
  → output policy (built-in AOAI filter + explicit analyze — layering decided, latency-budgeted)
  → [human approval gate ONLY for low-groundedness / sensitive / ambiguous-authz]
  → respond
       (+ Postgres checkpointer: durable memory; interrupt at TOP of its node)
       (+ idempotent audit per (thread_id, checkpoint_id))
```

## Milestones

### M0 — Thin vertical slice + foundations (INFRA + PROOF) ← we are here
Goal: `azd up` on a clean subscription provisions the stack **and** an
authenticated smoke slice proves the *whole chain* works — not just ARM.
- [ ] Repo scaffold; pyproject (uv, **pinned** LangGraph/model libs); Dockerfile;
      `azure.yaml`; **docker-compose** (local Postgres+pgvector dev loop);
      **minimal CI** (build + lint + test) at M0, not M4.
- [ ] Bicep: user-assigned MI; Log Analytics + App Insights; ACR; Azure OpenAI
      (chat + embedding, **model name+version as parameters**); Content Safety;
      **Azure AI Language** (for PII); Postgres Flexible Server (**burstable,
      cheapest SKU**, `azure.extensions=vector`, TLS-required, public+firewall
      default with a `useVnet` param); Container Apps env + app with **Easy Auth**;
      **RBAC role assignments** (least-privilege runtime vs migration identity).
- [ ] **Preflight script**: validate the chosen region supports AOAI + Content
      Safety + **groundedness** + Language + pgvector together; check model
      quota + RBAC; print an estimated baseline monthly cost.
- [ ] **Smoke slice** (`/smoke`, authenticated): MI-authenticated chat + embedding
      call, a Content Safety analyze, and Postgres connect → `CREATE EXTENSION
      vector` → a checkpoint-table migration + `SELECT`.
- [ ] Decide + prove Postgres auth (Entra token-refresh factory vs KV password).
- **Exit:** `azd up` cold → authenticated app live; `/smoke` green (identity,
  model, safety, pgvector, checkpoint all real); `.env` populated; `azd down
  --purge` documented; CI green.

### M1 — Core RAG + durable-state contract
- [ ] pgvector schema + **idempotent `CREATE EXTENSION` / migration** script.
- [ ] Ingestion: **`scripts/ingest.py` CLI** + a small **self-authored, licensed**
      sample corpus; stable doc/chunk IDs; idempotent re-index + delete. (File
      upload UI deferred.)
- [ ] LangGraph: retrieve → generate → respond **with `PostgresSaver` checkpointer
      + `thread_id` + state schema** (this is the API contract — built once here).
- [ ] Token-refreshing Postgres connection factory shared by pgvector + saver;
      explicit pool sizing (note PgBouncer transaction-pooling vs async-pipeline
      conflict).
- [ ] `/chat` with **server-issued opaque thread IDs** + owner checks; auth
      enforced; **non-streaming** v1.
- [ ] **Golden Q&A eval fixture** (~10 pairs) as an exit gate (seeded now, not M4).
- **Exit:** auth'd, thread-scoped, grounded answers over ingested docs; durable
  memory survives replica restarts; deployed.

### M2 — Safety layer (correct decomposition)
- [ ] Input: **Prompt Shields on user prompt AND retrieved chunks** (indirect
      injection); quarantine/exclude suspicious chunks; deterministic input caps.
- [ ] **PII via Azure AI Language** (detect/redact) — separate service.
- [ ] Output: decide **AOAI built-in content filter vs explicit Content Safety
      analyze** (don't blindly double-filter); **latency budget** for the chain.
- [ ] **Groundedness** with region-availability check + **LLM self-check fallback**.
- [ ] **fail-open/fail-closed** policy per check; **hard violations block (no HITL)**.
- **Exit:** direct + indirect injection tests pass; unsafe in/out is caught;
  safety chain within budget.

### M3 — Governance: HITL approval + privacy-safe audit
- [ ] LangGraph **`interrupt` at the TOP of its node** (avoid re-executing
      pre-interrupt code on resume); `/threads/{id}/resume` + idempotent
      `/approve` `/reject`; **approver role/authz**.
- [ ] HITL scope = low-groundedness / sensitive disclosure / ambiguous authz.
- [ ] **Audit**: versioned schema; pseudonymous actor IDs; redacted/hashed
      excerpts; correlation IDs; policy+model+prompt **version stamps**;
      retention + access controls; **idempotent per (thread_id, checkpoint_id)**;
      **separate store from operational telemetry**.
- **Exit:** a flagged turn pauses for an *authorized* approver and resumes on any
  replica; every turn is auditable; audit contains no raw PII.

### M4 — Evals + CI gating + governance mapping
- [ ] Expand eval corpus (adversarial, relevance, failure modes); Foundry hosted
      evals; **CI gates** on eval thresholds.
- [ ] `docs/governance-mapping.md`: which controls each feature **supports**
      (NIST AI RMF / EU AI Act / ISO 42001) with an explicit **non-compliance
      disclaimer** + customer obligations.
- **Exit:** CI green with eval gates; mapping documented honestly.

### M5 — Ship + distribute (authority loop)
- [ ] README + architecture diagram + screenshots + **cost table** +
      `azd down` + exact prerequisites + failure diagnostics.
- [ ] **ADRs** (`docs/adr/`) for locked decisions (one-Postgres-two-jobs,
      non-streaming, auth model, Postgres-auth choice).
- [ ] Validate `azd up` cold + rerun + partial-failure recovery + teardown across
      **≥2 regions**.
- [ ] Blog post on smartmobilehouse.com + LinkedIn; publish public + pin.
- **Exit:** live, documented, distributed.

## Cross-cutting requirements
- **Reproducibility:** pin LangGraph/langchain versions; **model name+version as
  Bicep params**; version prompts/policies/thresholds; stamp versions in every
  trace + audit event.
- **Operational readiness:** `/health` (liveness) **and** `/ready` (dependency
  readiness); bounded retries + timeouts; rate limiting; connection budgets;
  graceful degradation; backup/restore validation; scale-to-zero cold-start note.
- **Key Vault:** included **only** if the Postgres-password path is chosen;
  otherwise optional (keyless config via Container Apps settings).

## Risk register (owner / mitigation)
| Risk | Mitigation |
| --- | --- |
| **Region feature/model compatibility** (AOAI + Content Safety + groundedness + Language + pgvector rarely all in one region) | Preflight validates the combo per region; region is a Bicep param |
| **Azure OpenAI model-deployment quota** | Preflight checks quota; model+version parameterized; document the quota-request step |
| **Groundedness = preview** (region/lang/size/QPS limits, breaking changes) | Feature-flag it; LLM self-check fallback; pin API version |
| **Postgres Entra token expiry (~60 min)** | Token-refreshing connection factory; else KV password (documented) |
| **Postgres networking/DNS** (private endpoint complexity) | Public + firewall + TLS default; `useVnet` param as hardening path |
| **Idle / surprise cost** | Cheapest SKUs by default; log caps; cost table; `azd down --purge` |
| **Ingestion abuse / untrusted docs** | Authenticated admin ingestion only; validation; indirect-injection scanning |
| **Audit-data exposure / PII leakage** | Pseudonymized, redacted, access-controlled audit separate from telemetry |
| **Dependency + model version drift** | Pin libs; parameterize model version; version-stamp traces |
| **`azd up` reliability / teardown failures** | Preflight; test cold+rerun+teardown across ≥2 regions before publishing |

**Kill first:** the region/feature/quota combo (preflight) and the auth +
opaque-thread contract — both before building the chat flow.

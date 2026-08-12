# azure-governed-rag

A ready-to-deploy, **governed RAG assistant** on Azure AI Foundry, orchestrated
with **LangGraph** — authentication, safety, evals, audit, and a human-in-the-loop
approval gate wired in by default. Deploys with one command (`azd up`).

> Built and maintained by [Smart Mobile House](https://smartmobilehouse.com) —
> secure AI implementation for enterprise. **Status: early (M0).**

Most enterprise AI starters are a chatbot with an API key. This one is the
opposite: the boring, hard, enterprise parts are the point —
**identity (no keys), Prompt Shields, groundedness, PII handling, a privacy-safe
audit trail, and a human approval gate** — on portable, standards-based
foundations.

## What makes it "governed"
- **Authenticated by default** — Entra (Easy Auth); no anonymous endpoint.
- **Safety in and out** — Prompt Shields on user input *and retrieved context*,
  output filtering, and groundedness detection (with a fallback).
- **Keyless** — Managed Identity for models and services.
- **Human-in-the-loop** — a LangGraph `interrupt` approval gate for low-confidence
  or sensitive turns (hard safety violations are *not* overridable).
- **Auditable** — a versioned, pseudonymized audit record, separate from telemetry.
- **Honest governance mapping** — controls each feature *supports* under NIST AI
  RMF / EU AI Act / ISO 42001 (a mapping, **not** a compliance claim).

## Architecture (target)
```
authenticated request (owner-scoped thread)
  → Prompt Shields (input + retrieved chunks) + PII (Azure AI Language)
  → retrieve (pgvector) → generate (Azure OpenAI, Managed Identity)
  → groundedness → output policy → [approval gate if flagged] → respond
       (+ Postgres: pgvector store AND LangGraph checkpointer, isolated schemas)
       (+ idempotent, privacy-safe audit per turn)
```

## Stack
Azure Container Apps · Azure AI Foundry (Azure OpenAI) · Azure AI Content Safety ·
Azure AI Language · Azure Database for PostgreSQL (pgvector) · LangGraph ·
FastAPI · Bicep + `azd`.

## Deploy

**Prerequisites:** an Azure subscription with Azure OpenAI access + quota,
[`azd`](https://aka.ms/azd), Azure CLI (`az`), Docker, and `psql`.
Idle cost is **~$20–30/mo** (mostly Postgres) — run `azd down` when idle.

```bash
az login && azd auth login
azd up                 # preflight → provision (Bicep) → deploy → postprovision
                       #   (grants the managed identity a Postgres role,
                       #    enables pgvector, and configures Entra Easy Auth)
```

Then verify the whole keyless chain (chat, embedding, Content Safety, pgvector):

```bash
# /smoke is Entra-protected; pass a token for the app's registration:
curl -H "Authorization: Bearer $(az account get-access-token \
  --resource <APP_CLIENT_ID> --query accessToken -o tsv)" \
  "$(azd env get-value APP_URL)/smoke"
```

```bash
azd down --purge       # tear everything down (avoid idle spend)
```

## Local development
```bash
docker compose up -d          # local Postgres + pgvector
uv sync
az login                      # DefaultAzureCredential uses this for Azure services
uv run python -m uvicorn app.main:app --reload
```

## Status & roadmap
See [`docs/BUILD-PLAN.md`](docs/BUILD-PLAN.md). Current milestone: **M0 — thin
vertical slice + foundations** (prove `azd up` and the identity/model/safety/
pgvector/checkpoint chain end to end before building features).

## License
[MIT](LICENSE) © Smart Mobile House

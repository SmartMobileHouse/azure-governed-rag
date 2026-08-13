# 0006 — Single region (`swedencentral`)

**Status:** Accepted

## Context
This template needs Azure OpenAI (a current GA chat + embedding model), Content
Safety (incl. Prompt Shields), Language (PII), and PostgreSQL with pgvector — **in
the same region**. Few regions carry all of them together at the required model
versions. An early attempt to split AI services across regions (to keep Postgres
near the user, e.g. `polandcentral`) added deployment complexity and was rolled
back; Poland Central has none of the AI services.

## Decision
Deploy **everything to one region**, defaulting to **`swedencentral`**, which
carries the full set. The location is a Bicep parameter (`AZURE_LOCATION`), and a
preflight hook checks region/model/quota before provisioning.

## Consequences
- Simple, reproducible deploys; no cross-region latency or data-path questions in
  the reference architecture.
- Data residency is fixed to the chosen region — a constraint for deployments with
  in-country requirements (e.g., Polish data residency), which must find a region
  that carries the whole set or accept a split (and re-introduce that complexity).
- `azd` re-prompts for location after a teardown; picking a region without the
  full service set fails provisioning with `InvalidApiSetId`. Pin it with
  `azd env set AZURE_LOCATION swedencentral` (documented in the README).

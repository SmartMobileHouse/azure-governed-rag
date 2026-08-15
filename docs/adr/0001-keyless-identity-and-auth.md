# 0001 — Keyless managed identity + Entra Easy Auth

**Status:** Accepted

## Context
The template targets regulated/enterprise buyers, where leaked API keys and
connection strings are a primary audit finding. Azure OpenAI, Content Safety,
Language, and Postgres all support Entra (Azure AD) authentication.

## Decision
- Every outbound call authenticates as a **user-assigned managed identity** via
  `DefaultAzureCredential` — no keys or connection strings in code, config, or the
  image. Local auth is *disabled* on the Cognitive Services accounts and Postgres.
- Inbound traffic is fronted by **Entra Easy Auth** on the Container App;
  unauthenticated requests get `401` before app code runs. The app registration
  exposes an API and pre-authorizes the Azure CLI so a developer can mint a bearer
  token without an interactive consent prompt.

## Consequences
- No secret store is required for the core path; RBAC role assignments become the
  thing to review and rotate.
- Local development needs the developer's own identity granted the relevant
  Cognitive Services role (documented in the README).
- RBAC propagation on freshly created resources can lag minutes — deploys and
  first local calls occasionally need a short wait.
- A fresh managed identity's object id isn't known at deploy-start, so the
  Postgres role grant is done in a post-provision hook, not in Bicep.
- **Easy Auth is the authentication trust boundary.** The app reads the injected
  `X-MS-CLIENT-PRINCIPAL-NAME` (canonicalized) and requires it, but does not
  independently validate the Entra JWT — so it does *not* defend against Easy
  Auth being absent (a forged header would then be trusted). Container Apps
  strips client-supplied `X-MS-*` headers while Easy Auth is enabled, which is
  what makes the value trustworthy. In-app JWT validation (issuer / audience /
  signature via JWKS) is the hardening path for zero-trust or self-hosted runs.

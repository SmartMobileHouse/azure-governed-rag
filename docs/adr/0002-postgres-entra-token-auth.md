# 0002 — Postgres auth via Entra token, not a Key Vault password

**Status:** Accepted

## Context
PostgreSQL Flexible Server supports both password auth and Entra authentication.
Password auth would mean a secret to store, rotate, and protect (Key Vault +
access policies). Entra auth issues short-lived tokens tied to the managed
identity — consistent with [ADR 0001](0001-keyless-identity-and-auth.md).

## Decision
Use **Entra token authentication** for Postgres. The "password" handed to the
driver is a short-lived Entra access token (scope
`https://ossrdbms-aad.database.windows.net/.default`), cached and refreshed before
expiry. Password auth is disabled on the server. Locally, `docker-compose` Postgres
uses a static password so the same code path works without Azure.

## Consequences
- No database secret exists to leak; Key Vault is not on the critical path.
- Tokens expire (~60 min). The app opens short-lived connections so each picks up
  a current token; a long-lived pool would need a token-refreshing connection
  factory (a documented optimization, not yet implemented).
- If a deployment *must* use a password (e.g., a driver that can't take a token),
  Key Vault is the documented fallback — that's the one place a secret returns.

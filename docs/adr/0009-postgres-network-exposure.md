# 0009 — Postgres network exposure (v1 tradeoff)

**Status:** Accepted (v1 tradeoff)

## Context
The Container Apps environment (consumption) has no fixed egress IP, so the
simplest way to let the app reach PostgreSQL Flexible Server is the
`AllowAllAzureServices` firewall rule (start/end IP `0.0.0.0`). That admits
traffic from *any* Azure-hosted machine, not just this app — Entra-only
authentication is then the sole barrier at the network layer.

## Decision
Ship v1 with `AllowAllAzureServices` for a frictionless `azd up`, and treat the
network scope as an explicit, documented tradeoff — **not** a substitute for the
identity layer. Password auth is disabled and every connection is Entra-token +
`sslmode=verify-full`, so reachability alone grants nothing.

## Consequences
- One-command deploy with no VNet setup; good for a reference/starter.
- The database's network endpoint is broadly reachable; a Postgres CVE or a
  compromised authorized identity is remotely reachable. Acceptable for a
  template, **not** for production with sensitive data.
- Hardening path (documented, not yet implemented): VNet-integrated Container
  Apps + a delegated-subnet or private-endpoint PostgreSQL, gated behind a
  `useVnet` parameter, so the firewall can be closed to public Azure.

#!/usr/bin/env bash
# azd postprovision hook. Does the two things Bicep can't:
#   1) Grant the app's managed identity a Postgres role + enable pgvector
#      (a fresh UAMI's objectId isn't known at deploy-start, so this runs here).
#   2) Configure Entra "Easy Auth" on the Container App (needs an app registration,
#      which lives in Entra/Graph, not ARM).
# Requires: az CLI (logged in), psql. First cut — validate on your first azd up.
set -euo pipefail

: "${AZURE_ENV_NAME:?}"
: "${AZURE_RESOURCE_GROUP:?}"
: "${AZURE_TENANT_ID:?}"
: "${POSTGRES_SERVER_NAME:?}"
: "${POSTGRES_HOST:?}"
: "${POSTGRES_DB:?}"
: "${POSTGRES_USER:?}"        # the managed identity's Postgres role name
: "${SERVICE_WEB_NAME:?}"
: "${APP_URL:?}"

echo "── postprovision: Postgres grant + pgvector + Easy Auth ──"

# Locate psql. Homebrew's libpq is keg-only (unlinked) by default, so psql is
# often installed but not on PATH.
if ! command -v psql >/dev/null 2>&1; then
  for p in "$(brew --prefix libpq 2>/dev/null)/bin" /opt/homebrew/opt/libpq/bin /usr/local/opt/libpq/bin; do
    if [ -x "${p}/psql" ]; then PATH="${p}:${PATH}"; break; fi
  done
fi
command -v psql >/dev/null 2>&1 || {
  echo "  ! psql not found. Install: 'brew install libpq' (macOS) or 'postgresql-client' (Linux)."
  exit 127
}

# ── 1. Postgres: Entra admin (deployer) → grant MI role → pgvector ────────────
UPN="$(az ad signed-in-user show --query userPrincipalName -o tsv)"
OID="$(az ad signed-in-user show --query id -o tsv)"
echo "  Setting Entra admin: ${UPN}"
az postgres flexible-server microsoft-entra-admin create \
  --resource-group "${AZURE_RESOURCE_GROUP}" --server-name "${POSTGRES_SERVER_NAME}" \
  --display-name "${UPN}" --object-id "${OID}" --type User >/dev/null 2>&1 \
  || echo "  (Entra admin already set — continuing)"

echo "  Opening a temporary firewall rule for this machine (the hook runs locally)…"
MY_IP="$(curl -fsS https://api.ipify.org 2>/dev/null || curl -fsS https://ifconfig.me 2>/dev/null || true)"
[ -n "${MY_IP}" ] || { echo "  ! could not determine this machine's public IP"; exit 1; }
az postgres flexible-server firewall-rule create \
  --resource-group "${AZURE_RESOURCE_GROUP}" --server-name "${POSTGRES_SERVER_NAME}" \
  --name postprovision-client \
  --start-ip-address "${MY_IP}" --end-ip-address "${MY_IP}" >/dev/null

echo "  Granting managed-identity role '${POSTGRES_USER}' and enabling pgvector…"
PGPASSWORD="$(az account get-access-token \
  --resource https://ossrdbms-aad.database.windows.net \
  --query accessToken -o tsv)"
export PGPASSWORD
# The pgaadauth_* functions live only in the 'postgres' maintenance DB, and roles
# are cluster-wide — so create the Entra role there, then grant it the app DB.
psql "host=${POSTGRES_HOST} port=5432 dbname=postgres user=${UPN} sslmode=require" \
  -v ON_ERROR_STOP=1 <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${POSTGRES_USER}') THEN
    PERFORM pgaadauth_create_principal('${POSTGRES_USER}', false, false);
  END IF;
END \$\$;
GRANT ALL PRIVILEGES ON DATABASE "${POSTGRES_DB}" TO "${POSTGRES_USER}";
SQL

# Schema grant + pgvector are per-database, so run them inside the app DB.
psql "host=${POSTGRES_HOST} port=5432 dbname=${POSTGRES_DB} user=${UPN} sslmode=require" \
  -v ON_ERROR_STOP=1 <<SQL
GRANT ALL ON SCHEMA public TO "${POSTGRES_USER}";
CREATE EXTENSION IF NOT EXISTS vector;
SQL

# Runtime app→Postgres uses the Azure-services rule; drop this machine's temp rule.
az postgres flexible-server firewall-rule delete \
  --resource-group "${AZURE_RESOURCE_GROUP}" --server-name "${POSTGRES_SERVER_NAME}" \
  --name postprovision-client --yes >/dev/null 2>&1 || true

# ── 2. Easy Auth (Entra) on the Container App ────────────────────────────────
FQDN="${APP_URL#https://}"
APP_DISPLAY="agr-${AZURE_ENV_NAME}"
APP_ID="$(az ad app list --display-name "${APP_DISPLAY}" --query '[0].appId' -o tsv)"
if [ -z "${APP_ID}" ] || [ "${APP_ID}" = "null" ]; then
  echo "  Creating app registration ${APP_DISPLAY}…"
  APP_ID="$(az ad app create --display-name "${APP_DISPLAY}" \
    --web-redirect-uris "https://${FQDN}/.auth/login/aad/callback" \
    --query appId -o tsv)"
  az ad sp create --id "${APP_ID}" >/dev/null 2>&1 || true
fi
echo "  Enforcing Entra auth (client ${APP_ID})…"
az containerapp auth microsoft update \
  --resource-group "${AZURE_RESOURCE_GROUP}" --name "${SERVICE_WEB_NAME}" \
  --client-id "${APP_ID}" \
  --issuer "https://login.microsoftonline.com/${AZURE_TENANT_ID}/v2.0" \
  --yes >/dev/null
az containerapp auth update \
  --resource-group "${AZURE_RESOURCE_GROUP}" --name "${SERVICE_WEB_NAME}" \
  --unauthenticated-client-action Return401 \
  --redirect-provider azureactivedirectory >/dev/null

echo "── postprovision complete ──"
echo "  App (Entra-protected): ${APP_URL}"
echo "  Smoke test:  curl -H \"Authorization: Bearer \$(az account get-access-token --resource ${APP_ID} --query accessToken -o tsv)\" ${APP_URL}/smoke"

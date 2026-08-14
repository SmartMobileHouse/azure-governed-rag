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

# These names are interpolated into SQL/identifiers below — validate them as
# plain Postgres identifiers so a surprising env value can't change SQL meaning.
for _v in POSTGRES_USER POSTGRES_DB POSTGRES_SERVER_NAME; do
  case "${!_v}" in
    *[!A-Za-z0-9_-]*|"") echo "  ! ${_v} is not a valid identifier: '${!_v}'"; exit 1;;
  esac
done

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
RULE_NAME="postprovision-$$"
cleanup_firewall() {
  az postgres flexible-server firewall-rule delete \
    --resource-group "${AZURE_RESOURCE_GROUP}" --server-name "${POSTGRES_SERVER_NAME}" \
    --name "${RULE_NAME}" --yes >/dev/null 2>&1 || true
}
az postgres flexible-server firewall-rule create \
  --resource-group "${AZURE_RESOURCE_GROUP}" --server-name "${POSTGRES_SERVER_NAME}" \
  --name "${RULE_NAME}" \
  --start-ip-address "${MY_IP}" --end-ip-address "${MY_IP}" >/dev/null
# Remove the temp rule on ANY exit — success or failure — so it never lingers.
trap cleanup_firewall EXIT

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

# Runtime app→Postgres uses the Azure-services rule; the deployer's temp rule is
# removed by the EXIT trap (cleanup_firewall) whether or not later steps succeed.

# ── 2. Easy Auth (Entra) on the Container App ────────────────────────────────
FQDN="${APP_URL#https://}"
APP_DISPLAY="agr-${AZURE_ENV_NAME}"
# Exact-match the display name (not a prefix/substring) so a look-alike app
# registration can't be selected as the trusted Easy Auth client.
APP_ID="$(az ad app list --filter "displayName eq '${APP_DISPLAY}'" --query '[0].appId' -o tsv)"
if [ -z "${APP_ID}" ] || [ "${APP_ID}" = "null" ]; then
  echo "  Creating app registration ${APP_DISPLAY}…"
  APP_ID="$(az ad app create --display-name "${APP_DISPLAY}" \
    --web-redirect-uris "https://${FQDN}/.auth/login/aad/callback" \
    --query appId -o tsv)"
  az ad sp create --id "${APP_ID}" >/dev/null 2>&1 || true
fi
# Expose the app as an API resource so a bearer token can target it
# (aud = api://<appId>). Without this, tokens have no matching audience → 401.
API_AUDIENCE="api://${APP_ID}"
az ad app update --id "${APP_ID}" --identifier-uris "${API_AUDIENCE}" >/dev/null 2>&1 || true

# Expose a delegated scope and pre-authorize the Azure CLI, so a developer can
# mint a bearer token (aud = api://<appId>) with NO interactive consent:
#   az account get-access-token --resource api://<appId>
# Idempotent: reuse the existing scope id if user_impersonation already exists.
CLI_APP_ID="04b07795-8ddb-461a-bbee-02f9e1bf7b46"  # Microsoft Azure CLI (public client)
GRAPH="https://graph.microsoft.com/v1.0/applications(appId=%27${APP_ID}%27)"
SCOPE_ID="$(az rest --method GET --uri "${GRAPH}?\$select=api" \
  --query "api.oauth2PermissionScopes[?value=='user_impersonation'].id | [0]" -o tsv 2>/dev/null)"
if [ -z "${SCOPE_ID}" ] || [ "${SCOPE_ID}" = "null" ]; then
  SCOPE_ID="$(uuidgen 2>/dev/null | tr 'A-Z' 'a-z' || python3 -c 'import uuid;print(uuid.uuid4())')"
  az rest --method PATCH --uri "${GRAPH}" --headers "Content-Type=application/json" \
    --body "{\"api\":{\"oauth2PermissionScopes\":[{\"id\":\"${SCOPE_ID}\",\"isEnabled\":true,\"type\":\"User\",\"value\":\"user_impersonation\",\"adminConsentDisplayName\":\"Access azure-governed-rag\",\"adminConsentDescription\":\"Access azure-governed-rag as the signed-in user.\",\"userConsentDisplayName\":\"Access azure-governed-rag\",\"userConsentDescription\":\"Access azure-governed-rag on your behalf.\"}]}}" >/dev/null 2>&1 || true
fi
az rest --method PATCH --uri "${GRAPH}" --headers "Content-Type=application/json" \
  --body "{\"api\":{\"preAuthorizedApplications\":[{\"appId\":\"${CLI_APP_ID}\",\"delegatedPermissionIds\":[\"${SCOPE_ID}\"]}]}}" >/dev/null 2>&1 || true

echo "  Enforcing Entra auth (client ${APP_ID}, audience ${API_AUDIENCE})…"
az containerapp auth microsoft update \
  --resource-group "${AZURE_RESOURCE_GROUP}" --name "${SERVICE_WEB_NAME}" \
  --client-id "${APP_ID}" \
  --issuer "https://login.microsoftonline.com/${AZURE_TENANT_ID}/v2.0" \
  --allowed-token-audiences "${API_AUDIENCE}" \
  --yes >/dev/null
az containerapp auth update \
  --resource-group "${AZURE_RESOURCE_GROUP}" --name "${SERVICE_WEB_NAME}" \
  --unauthenticated-client-action Return401 \
  --redirect-provider azureactivedirectory >/dev/null

echo "── postprovision complete ──"
echo "  App (Entra-protected): ${APP_URL}"
echo "  Smoke test:  curl -H \"Authorization: Bearer \$(az account get-access-token --resource ${API_AUDIENCE} --query accessToken -o tsv)\" ${APP_URL}/smoke"

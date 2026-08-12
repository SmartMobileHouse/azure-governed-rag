#!/usr/bin/env bash
# Advisory preflight (azd preprovision hook). Never blocks the deploy — it warns.
# Verifies the chosen region can host Azure OpenAI + Content Safety + Language +
# Postgres together, checks OpenAI quota, and prints a cost note.
set -uo pipefail

LOCATION="${AZURE_LOCATION:-}"
echo "── azure-governed-rag preflight ──"

if ! az account show >/dev/null 2>&1; then
  echo "  ! Not logged in. Run 'az login' (and 'azd auth login')."
  exit 0
fi
echo "  Subscription: $(az account show --query name -o tsv)"

if [ -z "$LOCATION" ]; then
  echo "  AZURE_LOCATION not set yet — azd will prompt. Re-run after choosing a region."
  exit 0
fi
echo "  Region: $LOCATION"

echo "  Azure OpenAI models in $LOCATION (want: gpt-5-mini + text-embedding-3-small)…"
az cognitiveservices model list --location "$LOCATION" \
  --query "[?kind=='OpenAI'].model.name" -o tsv 2>/dev/null \
  | grep -iE "gpt-5-mini|text-embedding-3-small" \
  || echo "    ! expected models not listed here — verify names/versions or pick another region."

echo "  Azure OpenAI quota (TPM) in $LOCATION…"
az cognitiveservices usage list --location "$LOCATION" \
  --query "[?contains(name.value,'OpenAI')].{name:name.value,limit:limit,used:currentValue}" \
  -o table 2>/dev/null | head -15 || echo "    (quota query unavailable)"

echo "  Postgres Flexible Server SKU (Standard_B1ms) …"
az postgres flexible-server list-skus --location "$LOCATION" --query "[].name" -o tsv 2>/dev/null \
  | grep -q "Standard_B1ms" && echo "    OK: Standard_B1ms available" \
  || echo "    ! Standard_B1ms not listed in $LOCATION."

echo "  Note: Content Safety *groundedness* is preview + region-limited — verify separately."
cat <<'EOF'

  Estimated idle cost: ~$20-30/mo (Postgres B1ms ~$15-20 + ACR Basic ~$5 + logs).
  AI services are pay-per-use (~$0 idle). Run 'azd down --purge' to stop spend.
──────────────────────────────────
EOF
exit 0

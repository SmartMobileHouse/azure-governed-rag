targetScope = 'subscription'

// ─────────────────────────────────────────────────────────────────────────────
// azd entrypoint. Creates the resource group and delegates to resources.bicep.
// Outputs become environment variables azd writes to .azure/<env>/.env.
// ─────────────────────────────────────────────────────────────────────────────

@minLength(1)
@maxLength(64)
@description('azd environment name; used to derive resource names.')
param environmentName string

@minLength(1)
@description('Primary region for all resources. Must support Azure OpenAI + Content Safety + Language + PostgreSQL together (see the preflight script).')
param location string

@description('Object id of the deploying principal (azd sets AZURE_PRINCIPAL_ID). Added as a Postgres Entra admin so a human can run migrations.')
param principalId string = ''

@description('Azure OpenAI chat model + version (parameterized for reproducibility). gpt-4o-mini/2024-07-18 is deprecating — using a current GA model.')
param chatModelName string = 'gpt-5-mini'
param chatModelVersion string = '2025-08-07'

@description('Azure OpenAI embedding model + version.')
param embeddingModelName string = 'text-embedding-3-small'
param embeddingModelVersion string = '1'

@description('Per-deployment TPM capacity (thousands). Keep modest to fit quota.')
param chatCapacity int = 20
param embeddingCapacity int = 20

@description('Deployment SKU. GlobalStandard is the most broadly available (e.g. text-embedding-3-small has no regional Standard in Sweden Central).')
param deploymentSku string = 'GlobalStandard'

var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName }

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module resources 'resources.bicep' = {
  name: 'resources'
  scope: rg
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
    chatModelName: chatModelName
    chatModelVersion: chatModelVersion
    embeddingModelName: embeddingModelName
    embeddingModelVersion: embeddingModelVersion
    chatCapacity: chatCapacity
    embeddingCapacity: embeddingCapacity
    deploymentSku: deploymentSku
  }
}

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = subscription().tenantId
output AZURE_RESOURCE_GROUP string = rg.name
// Exposed for the postprovision hook (Entra admin + UAMI grant + pgvector + auth).
output AZURE_PRINCIPAL_ID string = principalId
output POSTGRES_SERVER_NAME string = resources.outputs.POSTGRES_SERVER_NAME
output SERVICE_WEB_NAME string = resources.outputs.SERVICE_WEB_NAME
output APP_URL string = resources.outputs.APP_URL
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.AZURE_CONTAINER_REGISTRY_ENDPOINT
output AZURE_CLIENT_ID string = resources.outputs.AZURE_CLIENT_ID
output AZURE_OPENAI_ENDPOINT string = resources.outputs.AZURE_OPENAI_ENDPOINT
output AZURE_OPENAI_CHAT_DEPLOYMENT string = resources.outputs.AZURE_OPENAI_CHAT_DEPLOYMENT
output AZURE_OPENAI_EMBEDDING_DEPLOYMENT string = resources.outputs.AZURE_OPENAI_EMBEDDING_DEPLOYMENT
output AZURE_OPENAI_API_VERSION string = '2024-10-21'
output CONTENT_SAFETY_ENDPOINT string = resources.outputs.CONTENT_SAFETY_ENDPOINT
output LANGUAGE_ENDPOINT string = resources.outputs.LANGUAGE_ENDPOINT
output POSTGRES_HOST string = resources.outputs.POSTGRES_HOST
output POSTGRES_DB string = resources.outputs.POSTGRES_DB
output POSTGRES_USER string = resources.outputs.POSTGRES_USER

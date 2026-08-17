// ─────────────────────────────────────────────────────────────────────────────
// All resources for the governed RAG stack (M0).
// Keyless throughout: Cognitive Services use Entra tokens (local auth disabled),
// PostgreSQL is Entra-only (password auth disabled). The app runs as a
// user-assigned managed identity.
//
// NOTE: first cut — the M0 exit criterion is a successful cold `azd up`, so
// expect to iterate on region/quota/API-version specifics on first deploy.
// ─────────────────────────────────────────────────────────────────────────────

param location string
param tags object
param resourceToken string
param chatModelName string
param chatModelVersion string
param embeddingModelName string
param embeddingModelVersion string
param chatCapacity int
param embeddingCapacity int
param deploymentSku string

@secure()
param auditHashKey string = ''
param hitlApproverEmails string = ''

var abbrs = {
  law: 'log-${resourceToken}'
  appi: 'appi-${resourceToken}'
  uami: 'id-${resourceToken}'
  acr: 'acr${resourceToken}'
  openai: 'oai-${resourceToken}'
  safety: 'cs-${resourceToken}'
  language: 'lang-${resourceToken}'
  pg: 'psql-${resourceToken}'
  cae: 'cae-${resourceToken}'
  app: 'ca-web-${resourceToken}'
}

// Built-in role definition ids
var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  openaiUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd' // Cognitive Services OpenAI User
  cognitiveUser: 'a97b65f3-24c7-4388-baec-2e87135dc908' // Cognitive Services User
}

// ── Observability ────────────────────────────────────────────────────────────
resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: abbrs.law
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    features: { immediatePurgeDataOn30Days: true }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: abbrs.appi
  location: location
  tags: tags
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: law.id }
}

// ── Identity ─────────────────────────────────────────────────────────────────
resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: abbrs.uami
  location: location
  tags: tags
}

// ── Container Registry ───────────────────────────────────────────────────────
resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: abbrs.acr
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, uami.id, roles.acrPull)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ── Azure OpenAI (Foundry) — keyless ─────────────────────────────────────────
resource openai 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: abbrs.openai
  location: location
  tags: tags
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: abbrs.openai
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

@batchSize(1) // model deployments must be created serially
resource openaiDeployments 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = [
  for d in [
    { name: chatModelName, model: chatModelName, version: chatModelVersion, capacity: chatCapacity }
    { name: embeddingModelName, model: embeddingModelName, version: embeddingModelVersion, capacity: embeddingCapacity }
  ]: {
    parent: openai
    name: d.name
    sku: { name: deploymentSku, capacity: d.capacity }
    properties: {
      model: { format: 'OpenAI', name: d.model, version: d.version }
    }
  }
]

resource openaiRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(openai.id, uami.id, roles.openaiUser)
  scope: openai
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.openaiUser)
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ── Content Safety — keyless ─────────────────────────────────────────────────
resource safety 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: abbrs.safety
  location: location
  tags: tags
  kind: 'ContentSafety'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: abbrs.safety
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

resource safetyRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(safety.id, uami.id, roles.cognitiveUser)
  scope: safety
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveUser)
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ── Azure AI Language (PII) — keyless ────────────────────────────────────────
resource language 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: abbrs.language
  location: location
  tags: tags
  kind: 'TextAnalytics'
  sku: { name: 'S' }
  properties: {
    customSubDomainName: abbrs.language
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

resource languageRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(language.id, uami.id, roles.cognitiveUser)
  scope: language
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveUser)
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ── PostgreSQL Flexible Server — Entra-only (keyless), pgvector ───────────────
// Control-plane ops on a flex server must be serialized, so the child resources
// below are chained with dependsOn.
resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: abbrs.pg
  location: location
  tags: tags
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '16'
    storage: { storageSizeGB: 32 }
    authConfig: {
      activeDirectoryAuth: 'Enabled'
      passwordAuth: 'Disabled'
      tenantId: subscription().tenantId
    }
    highAvailability: { mode: 'Disabled' }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
  }
}

resource pgExtensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: postgres
  name: 'azure.extensions'
  properties: { value: 'VECTOR', source: 'user-override' }
}

resource pgDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: 'appdb'
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
  dependsOn: [ pgExtensions ]
}

// Allow other Azure services (e.g. the container app) to reach the server.
resource pgFirewall 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: postgres
  name: 'AllowAllAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
  dependsOn: [ pgDatabase ]
}

// NOTE: Entra admin + granting the app's managed identity a Postgres role +
// `CREATE EXTENSION vector` are done in scripts/postprovision.sh (an azd hook),
// because a newly-created UAMI's objectId isn't known at deployment start and
// `az` resolves the principal + runs the SQL cleanly.

// ── Container Apps ───────────────────────────────────────────────────────────
resource cae 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: abbrs.cae
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
  }
}

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: abbrs.app
  location: location
  // azd matches the service in azure.yaml by this tag.
  tags: union(tags, { 'azd-service-name': 'web' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${uami.id}': {} }
  }
  properties: {
    managedEnvironmentId: cae.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, targetPort: 8000, transport: 'auto' }
      registries: [ { server: acr.properties.loginServer, identity: uami.id } ]
      // HMAC pepper for audit/ownership pseudonyms. Normally a random value the
      // preflight hook generated and persisted in the azd env (auditHashKey). The
      // guid() is only an ARM-safe fallback if that wasn't set; a Key Vault secret
      // reference is the stronger hardening path (see governance-mapping.md).
      secrets: [
        {
          name: 'audit-hash-key'
          value: !empty(auditHashKey) ? auditHashKey : guid(subscription().id, resourceGroup().id, 'audit-hash-key')
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'web'
          // Placeholder; azd replaces this with the built image on deploy.
          image: 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
          resources: { cpu: json('0.5'), memory: '1.0Gi' }
          env: [
            { name: 'AZURE_CLIENT_ID', value: uami.properties.clientId }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
            { name: 'AZURE_OPENAI_ENDPOINT', value: openai.properties.endpoint }
            { name: 'AZURE_OPENAI_CHAT_DEPLOYMENT', value: chatModelName }
            { name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT', value: embeddingModelName }
            { name: 'CONTENT_SAFETY_ENDPOINT', value: safety.properties.endpoint }
            { name: 'LANGUAGE_ENDPOINT', value: language.properties.endpoint }
            { name: 'POSTGRES_HOST', value: postgres.properties.fullyQualifiedDomainName }
            { name: 'POSTGRES_DB', value: 'appdb' }
            { name: 'POSTGRES_USER', value: uami.name }
            { name: 'AUDIT_HASH_KEY', secretRef: 'audit-hash-key' }
            { name: 'HITL_APPROVER_EMAILS', value: hitlApproverEmails }
          ]
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 2 }
    }
  }
  dependsOn: [ acrPull ]
}

// ── Outputs (azd writes these to the env .env) ───────────────────────────────
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = acr.properties.loginServer
output AZURE_CLIENT_ID string = uami.properties.clientId
output AZURE_OPENAI_ENDPOINT string = openai.properties.endpoint
output AZURE_OPENAI_CHAT_DEPLOYMENT string = chatModelName
output AZURE_OPENAI_EMBEDDING_DEPLOYMENT string = embeddingModelName
output CONTENT_SAFETY_ENDPOINT string = safety.properties.endpoint
output LANGUAGE_ENDPOINT string = language.properties.endpoint
output POSTGRES_HOST string = postgres.properties.fullyQualifiedDomainName
output POSTGRES_DB string = 'appdb'
output POSTGRES_USER string = uami.name
output POSTGRES_SERVER_NAME string = postgres.name
output SERVICE_WEB_NAME string = app.name
output APP_URL string = 'https://${app.properties.configuration.ingress.fqdn}'

// Parameters
@description('Location for all resources')
param location string = resourceGroup().location

@description('Name of the Function App')
param functionAppName string

@description('Name of the App Service Plan')
param appServicePlanName string

@description('Use existing App Service Plan instead of creating new one')
param useExistingAppServicePlan bool = false

@description('Name of the Storage Account for Function App')
param functionStorageAccountName string

@description('Name of the Application Insights')
param appInsightsName string

@description('Name of the Data Storage Account (source data)')
param dataStorageAccountName string

@description('Name of the Data Storage Container')
param dataStorageContainerName string

@description('Azure Search Service Name')
param searchServiceName string

@description('Azure Search Index Name')
param searchIndexName string

@description('Azure OpenAI Service Name')
param openAiServiceName string

@description('Azure Document Intelligence Service Name')
param documentIntelligenceServiceName string

@description('Azure Cognitive Services Name (if using multi-service)')
param cognitiveServicesName string = ''

@description('Resource Group of Data Storage Account')
param dataStorageResourceGroup string = resourceGroup().name

@description('Subscription ID')
param subscriptionId string = subscription().subscriptionId

// Existing resources references
resource dataStorageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: dataStorageAccountName
  scope: resourceGroup(subscriptionId, dataStorageResourceGroup)
}

resource searchService 'Microsoft.Search/searchServices@2023-11-01' existing = {
  name: searchServiceName
}

resource openAiService 'Microsoft.CognitiveServices/accounts@2023-10-01-preview' existing = {
  name: openAiServiceName
}

resource documentIntelligenceService 'Microsoft.CognitiveServices/accounts@2023-10-01-preview' existing = {
  name: documentIntelligenceServiceName
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

resource appServicePlan 'Microsoft.Web/serverfarms@2023-01-01' existing = if (useExistingAppServicePlan) {
  name: appServicePlanName
}

// New resources
resource functionStorageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: functionStorageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource newAppServicePlan 'Microsoft.Web/serverfarms@2023-01-01' = if (!useExistingAppServicePlan) {
  name: appServicePlanName
  location: location
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  kind: 'functionapp'
  properties: {
    reserved: true // Required for Linux
  }
}

resource functionApp 'Microsoft.Web/sites@2023-01-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: useExistingAppServicePlan ? appServicePlan.id : newAppServicePlan.id
    reserved: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appSettings: [
        {
          name: 'AzureWebJobsStorage'
          value: 'DefaultEndpointsProtocol=https;AccountName=${functionStorageAccount.name};EndpointSuffix=${environment().suffixes.storage};AccountKey=${functionStorageAccount.listKeys().keys[0].value}'
        }
        {
          name: 'WEBSITE_CONTENTAZUREFILECONNECTIONSTRING'
          value: 'DefaultEndpointsProtocol=https;AccountName=${functionStorageAccount.name};EndpointSuffix=${environment().suffixes.storage};AccountKey=${functionStorageAccount.listKeys().keys[0].value}'
        }
        {
          name: 'WEBSITE_CONTENTSHARE'
          value: toLower(functionAppName)
        }
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'APPINSIGHTS_INSTRUMENTATIONKEY'
          value: appInsights.properties.InstrumentationKey
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsights.properties.ConnectionString
        }
        // Azure subscription and resource identifiers
        {
          name: 'AZURE_SUBSCRIPTION_ID'
          value: subscriptionId
        }
        {
          name: 'AZURE_STORAGE_ACCOUNT'
          value: dataStorageAccountName
        }
        {
          name: 'AZURE_STORAGE_CONTAINER'
          value: dataStorageContainerName
        }
        {
          name: 'AZURE_STORAGE_RESOURCE_GROUP'
          value: dataStorageResourceGroup
        }
        // Azure Search configuration
        {
          name: 'AZURE_SEARCH_SERVICE'
          value: searchServiceName
        }
        {
          name: 'AZURE_SEARCH_INDEX'
          value: searchIndexName
        }
        {
          name: 'AZURE_SEARCH_FIELD_NAME_EMBEDDING'
          value: 'embedding3'
        }
        // Azure OpenAI configuration
        {
          name: 'AZURE_OPENAI_SERVICE'
          value: openAiServiceName
        }
        {
          name: 'AZURE_OPENAI_ENDPOINT'
          value: openAiService.properties.endpoint
        }
        {
          name: 'OPENAI_HOST'
          value: 'azure'
        }
        {
          name: 'AZURE_OPENAI_EMB_MODEL_NAME'
          value: 'text-embedding-3-large'
        }
        {
          name: 'AZURE_OPENAI_EMB_DEPLOYMENT'
          value: 'text-embedding-3-large'
        }
        {
          name: 'AZURE_OPENAI_EMB_DIMENSIONS'
          value: '3072'
        }
        {
          name: 'AZURE_OPENAI_CHATGPT_MODEL'
          value: 'gpt-4o'
        }
        {
          name: 'AZURE_OPENAI_CHATGPT_DEPLOYMENT'
          value: 'gpt-4o'
        }
        // Document Intelligence configuration
        {
          name: 'AZURE_DOCUMENTINTELLIGENCE_SERVICE'
          value: documentIntelligenceServiceName
        }
        // Ingestion settings
        {
          name: 'TimerSchedule'
          value: '0 */30 * * * *'
        }
        {
          name: 'INGESTION_LOOKBACK_HOURS'
          value: '24'
        }
        {
          name: 'USE_FEATURE_INT_VECTORIZATION'
          value: 'false'
        }
        {
          name: 'USE_MULTIMODAL'
          value: 'false'
        }
        {
          name: 'USE_VECTORS'
          value: 'true'
        }
        {
          name: 'USE_AGENTIC_KNOWLEDGEBASE'
          value: 'false'
        }
        {
          name: 'AZURE_USE_AUTHENTICATION'
          value: 'false'
        }
        {
          name: 'AZURE_ENFORCE_ACCESS_CONTROL'
          value: 'false'
        }
        {
          name: 'AZURE_ENABLE_GLOBAL_DOCUMENT_ACCESS'
          value: 'true'
        }
        {
          name: 'USE_LOCAL_PDF_PARSER'
          value: 'false'
        }
        {
          name: 'USE_LOCAL_HTML_PARSER'
          value: 'false'
        }
      ]
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
    }
    httpsOnly: true
  }
}

// Role Assignments using modules for cross-resource-group support

// Storage Blob Data Contributor role for Data Storage Account
module storageRoleAssignment 'role-assignment.bicep' = {
  name: 'storage-role-${uniqueString(functionApp.id, dataStorageAccountName)}'
  scope: resourceGroup(subscriptionId, dataStorageResourceGroup)
  params: {
    principalId: functionApp.identity.principalId
    roleDefinitionId: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe' // Storage Blob Data Contributor
    targetResourceName: dataStorageAccountName
    targetResourceType: 'Microsoft.Storage/storageAccounts'
  }
}

// Search Index Data Contributor role for Search Service
module searchRoleAssignment 'role-assignment.bicep' = {
  name: 'search-role-${uniqueString(functionApp.id, searchServiceName)}'
  scope: resourceGroup()
  params: {
    principalId: functionApp.identity.principalId
    roleDefinitionId: '8ebe5a00-799e-43f5-93ac-243d3dce84a7' // Search Index Data Contributor
    targetResourceName: searchServiceName
    targetResourceType: 'Microsoft.Search/searchServices'
  }
}

// Cognitive Services OpenAI User role for OpenAI Service
module openAiRoleAssignment 'role-assignment.bicep' = {
  name: 'openai-role-${uniqueString(functionApp.id, openAiServiceName)}'
  scope: resourceGroup()
  params: {
    principalId: functionApp.identity.principalId
    roleDefinitionId: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd' // Cognitive Services OpenAI User
    targetResourceName: openAiServiceName
    targetResourceType: 'Microsoft.CognitiveServices/accounts'
  }
}

// Cognitive Services User role for Document Intelligence Service
module documentIntelligenceRoleAssignment 'role-assignment.bicep' = {
  name: 'docintel-role-${uniqueString(functionApp.id, documentIntelligenceServiceName)}'
  scope: resourceGroup()
  params: {
    principalId: functionApp.identity.principalId
    roleDefinitionId: 'a97b65f3-24c7-4388-baec-2e87135dc908' // Cognitive Services User
    targetResourceName: documentIntelligenceServiceName
    targetResourceType: 'Microsoft.CognitiveServices/accounts'
  }
}

// Outputs
output functionAppName string = functionApp.name
output functionAppPrincipalId string = functionApp.identity.principalId
output functionAppUrl string = 'https://${functionApp.properties.defaultHostName}'

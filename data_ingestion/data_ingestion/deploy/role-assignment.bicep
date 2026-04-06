// Module for assigning roles to resources in different resource groups
// This is needed because role assignments must match the scope of the target resource

@description('Principal ID of the managed identity')
param principalId string

@description('Role Definition ID (GUID)')
param roleDefinitionId string

@description('Name of the target resource')
param targetResourceName string

@description('Type of the target resource (e.g., Microsoft.Storage/storageAccounts)')
param targetResourceType string

// Create the existing resource reference
resource targetResource 'Microsoft.Storage/storageAccounts@2023-01-01' existing = if (targetResourceType == 'Microsoft.Storage/storageAccounts') {
  name: targetResourceName
}

resource targetSearchService 'Microsoft.Search/searchServices@2023-11-01' existing = if (targetResourceType == 'Microsoft.Search/searchServices') {
  name: targetResourceName
}

resource targetCognitiveService 'Microsoft.CognitiveServices/accounts@2023-10-01-preview' existing = if (targetResourceType == 'Microsoft.CognitiveServices/accounts') {
  name: targetResourceName
}

// Assign the role - Storage Account
resource roleAssignmentStorage'Microsoft.Authorization/roleAssignments@2022-04-01' = if (targetResourceType == 'Microsoft.Storage/storageAccounts') {
  name: guid(principalId, targetResource.id, roleDefinitionId)
  scope: targetResource
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleDefinitionId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// Assign the role - Search Service
resource roleAssignmentSearch 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (targetResourceType == 'Microsoft.Search/searchServices') {
  name: guid(principalId, targetSearchService.id, roleDefinitionId)
  scope: targetSearchService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleDefinitionId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// Assign the role - Cognitive Services
resource roleAssignmentCognitive 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (targetResourceType == 'Microsoft.CognitiveServices/accounts') {
  name: guid(principalId, targetCognitiveService.id, roleDefinitionId)
  scope: targetCognitiveService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleDefinitionId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

output roleAssignmentId string = targetResourceType == 'Microsoft.Storage/storageAccounts' ? roleAssignmentStorage.id : (targetResourceType == 'Microsoft.Search/searchServices' ? roleAssignmentSearch.id : roleAssignmentCognitive.id)

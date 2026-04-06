# Deploy Function App with Managed Identity and Role Assignments

This Bicep template deploys an Azure Function App with:
- **System-assigned Managed Identity**
- **Required role assignments** for secure access to Azure resources

## Role Assignments

The Function App is automatically granted the following roles:

### 1. Storage Blob Data Contributor
- **Resource**: Data Storage Account (source data)
- **Role ID**: `ba92f5b4-2d11-453d-a403-e96b0029c9fe`
- **Purpose**: Read and write access to blob storage for data ingestion

### 2. Search Index Data Contributor
- **Resource**: Azure AI Search Service
- **Role ID**: `8ebe5a00-799e-43f5-93ac-243d3dce84a7`
- **Purpose**: Create, update, and delete search index documents

### 3. Cognitive Services OpenAI User
- **Resource**: Azure OpenAI Service
- **Role ID**: `5e0bd9bd-7b93-4f28-af87-19fc36ad61bd`
- **Purpose**: Access OpenAI embeddings and chat models

### 4. Cognitive Services User
- **Resource**: Document Intelligence Service
- **Role ID**: `a97b65f3-24c7-4388-baec-2e87135dc908`
- **Purpose**: Use Document Intelligence for document parsing

## Deployment

### Prerequisites
1. Azure CLI installed and authenticated
2. Existing Azure resources:
   - Data Storage Account with container
   - Azure AI Search Service
   - Azure OpenAI Service with deployed models
   - Document Intelligence Service

### Deploy using Azure CLI

```bash
# Set variables
RESOURCE_GROUP="rg-search-openai-rag"
LOCATION="eastus"
FUNCTION_APP_NAME="func-data-ingestion-001"
APP_SERVICE_PLAN_NAME="asp-data-ingestion"
FUNCTION_STORAGE_NAME="stfunc$(openssl rand -hex 4)"
APP_INSIGHTS_NAME="appi-data-ingestion"

# Existing resources
DATA_STORAGE_NAME="stdatasource001"
DATA_CONTAINER_NAME="documents"
SEARCH_SERVICE_NAME="srch-openai-rag"
SEARCH_INDEX_NAME="documents-index"
OPENAI_SERVICE_NAME="openai-rag-service"
DOC_INTEL_SERVICE_NAME="docintel-service"

# Deploy
az deployment group create \
  --resource-group $RESOURCE_GROUP \
  --template-file function-app.bicep \
  --parameters \
    functionAppName=$FUNCTION_APP_NAME \
    appServicePlanName=$APP_SERVICE_PLAN_NAME \
    functionStorageAccountName=$FUNCTION_STORAGE_NAME \
    appInsightsName=$APP_INSIGHTS_NAME \
    dataStorageAccountName=$DATA_STORAGE_NAME \
    dataStorageContainerName=$DATA_CONTAINER_NAME \
    searchServiceName=$SEARCH_SERVICE_NAME \
    searchIndexName=$SEARCH_INDEX_NAME \
    openAiServiceName=$OPENAI_SERVICE_NAME \
    documentIntelligenceServiceName=$DOC_INTEL_SERVICE_NAME \
    location=$LOCATION
```

### Deploy using parameters file

Create a `parameters.json` file:

```json
{
  "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
  "contentVersion": "1.0.0.0",
  "parameters": {
    "functionAppName": {
      "value": "func-data-ingestion-001"
    },
    "appServicePlanName": {
      "value": "asp-data-ingestion"
    },
    "functionStorageAccountName": {
      "value": "stfuncxxxxxxxxx"
    },
    "appInsightsName": {
      "value": "appi-data-ingestion"
    },
    "dataStorageAccountName": {
      "value": "stdatasource001"
    },
    "dataStorageContainerName": {
      "value": "documents"
    },
    "searchServiceName": {
      "value": "srch-openai-rag"
    },
    "searchIndexName": {
      "value": "documents-index"
    },
    "openAiServiceName": {
      "value": "openai-rag-service"
    },
    "documentIntelligenceServiceName": {
      "value": "docintel-service"
    }
  }
}
```

Then deploy:

```bash
az deployment group create \
  --resource-group $RESOURCE_GROUP \
  --template-file function-app.bicep \
  --parameters @parameters.json
```

## Post-Deployment

### 1. Deploy Function Code

```bash
# Package and deploy
cd ..  # Navigate to function app root
func azure functionapp publish $FUNCTION_APP_NAME
```

### 2. Verify Role Assignments

```bash
# Get Function App Principal ID
PRINCIPAL_ID=$(az functionapp identity show \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query principalId -o tsv)

# List role assignments
az role assignment list \
  --assignee $PRINCIPAL_ID \
  --all \
  --output table
```

### 3. Test the Function

The function runs on a timer (every 30 minutes by default). To test immediately:

```bash
# Trigger manually via Azure portal or CLI
az functionapp function invoke \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --function-name DataIngestionFunction
```

### 4. Monitor Execution

```bash
# Stream logs
func azure functionapp logstream $FUNCTION_APP_NAME

# Or use Azure CLI
az webapp log tail \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP
```

## Configuration

### Timer Schedule

Edit `DataIngestionFunction/function.json` to change the schedule:

```json
{
  "schedule": "0 */30 * * * *"  // Every 30 minutes
}
```

Common schedules:
- Every hour: `"0 0 * * * *"`
- Every 6 hours: `"0 0 */6 * * *"`
- Daily at 2 AM: `"0 0 2 * * *"`

### Environment Variables

Update application settings via Azure CLI:

```bash
az functionapp config appsettings set \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --settings \
    "INGESTION_LOOKBACK_HOURS=48" \
    "USE_VECTORS=true" \
    "VERBOSE_LOGGING=true"
```

## Troubleshooting

### Check Managed Identity

```bash
az functionapp identity show \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP
```

### Verify Role Assignments

```bash
# Storage
az role assignment list \
  --scope "/subscriptions/{subscription-id}/resourceGroups/{rg}/providers/Microsoft.Storage/storageAccounts/{storage-name}" \
  --assignee $PRINCIPAL_ID

# Search
az role assignment list \
  --scope "/subscriptions/{subscription-id}/resourceGroups/{rg}/providers/Microsoft.Search/searchServices/{search-name}" \
  --assignee $PRINCIPAL_ID
```

### View Function Logs

```bash
# Application Insights query
az monitor app-insights query \
  --app $APP_INSIGHTS_NAME \
  --resource-group $RESOURCE_GROUP \
  --analytics-query "traces | where operation_Name == 'DataIngestionFunction' | order by timestamp desc | take 50"
```

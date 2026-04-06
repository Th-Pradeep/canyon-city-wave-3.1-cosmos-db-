# Deploy Azure Function App for Data Ingestion with Managed Identity
# PowerShell deployment script for Windows

$ErrorActionPreference = "Stop"

# Colors for output
function Write-ColorOutput($ForegroundColor) {
    $fc = $host.UI.RawUI.ForegroundColor
    $host.UI.RawUI.ForegroundColor = $ForegroundColor
    if ($args) {
        Write-Output $args
    }
    $host.UI.RawUI.ForegroundColor = $fc
}

Write-ColorOutput Green "================================================"
Write-ColorOutput Green "Azure Function App Deployment Script"
Write-ColorOutput Green "Data Ingestion with Managed Identity"
Write-ColorOutput Green "================================================"
Write-Output ""

# Check if Azure CLI is installed
try {
    az version | Out-Null
} catch {
    Write-ColorOutput Red "Error: Azure CLI is not installed"
    Write-Output "Please install it from: https://learn.microsoft.com/cli/azure/install-azure-cli"
    exit 1
}

# Check if Azure Functions Core Tools is installed
try {
    func --version | Out-Null
} catch {
    Write-ColorOutput Red "Error: Azure Functions Core Tools is not installed"
    Write-Output "Please install it from: https://learn.microsoft.com/azure/azure-functions/functions-run-local"
    exit 1
}

# Prompt for deployment parameters
Write-ColorOutput Yellow "Please provide deployment parameters:"
Write-Output ""

$RESOURCE_GROUP = Read-Host "Resource Group Name"
$LOCATION = Read-Host "Location (default: eastus)"
if ([string]::IsNullOrWhiteSpace($LOCATION)) { $LOCATION = "eastus" }

$FUNCTION_APP_NAME = Read-Host "Function App Name"
$APP_SERVICE_PLAN_NAME = Read-Host "App Service Plan Name (default: asp-$FUNCTION_APP_NAME)"
if ([string]::IsNullOrWhiteSpace($APP_SERVICE_PLAN_NAME)) { $APP_SERVICE_PLAN_NAME = "asp-$FUNCTION_APP_NAME" }

# Generate unique storage account name
$RANDOM_SUFFIX = -join ((48..57) + (97..102) | Get-Random -Count 6 | ForEach-Object {[char]$_})
$DEFAULT_FUNC_STORAGE = "stfunc$RANDOM_SUFFIX"
$FUNCTION_STORAGE_NAME = Read-Host "Function Storage Account Name (default: $DEFAULT_FUNC_STORAGE)"
if ([string]::IsNullOrWhiteSpace($FUNCTION_STORAGE_NAME)) { $FUNCTION_STORAGE_NAME = $DEFAULT_FUNC_STORAGE }

$APP_INSIGHTS_NAME = Read-Host "App Insights Name (default: appi-$FUNCTION_APP_NAME)"
if ([string]::IsNullOrWhiteSpace($APP_INSIGHTS_NAME)) { $APP_INSIGHTS_NAME = "appi-$FUNCTION_APP_NAME" }

Write-Output ""
Write-ColorOutput Yellow "Existing Azure Resources:"
$DATA_STORAGE_NAME = Read-Host "Data Storage Account Name"
$DATA_CONTAINER_NAME = Read-Host "Data Storage Container Name"
$DATA_STORAGE_RG = Read-Host "Data Storage Resource Group (default: $RESOURCE_GROUP)"
if ([string]::IsNullOrWhiteSpace($DATA_STORAGE_RG)) { $DATA_STORAGE_RG = $RESOURCE_GROUP }

$SEARCH_SERVICE_NAME = Read-Host "Search Service Name"
$SEARCH_INDEX_NAME = Read-Host "Search Index Name"
$OPENAI_SERVICE_NAME = Read-Host "OpenAI Service Name"
$DOC_INTEL_SERVICE_NAME = Read-Host "Document Intelligence Service Name"

Write-Output ""
Write-ColorOutput Green "Deployment Configuration:"
Write-Output "Resource Group: $RESOURCE_GROUP"
Write-Output "Location: $LOCATION"
Write-Output "Function App: $FUNCTION_APP_NAME"
Write-Output "Data Storage: $DATA_STORAGE_NAME/$DATA_CONTAINER_NAME"
Write-Output "Search Service: $SEARCH_SERVICE_NAME"
Write-Output ""

$CONFIRM = Read-Host "Proceed with deployment? (yes/no)"
if ($CONFIRM -ne "yes") {
    Write-Output "Deployment cancelled"
    exit 0
}

# Get subscription ID
$SUBSCRIPTION_ID = az account show --query id -o tsv
Write-Output ""
Write-ColorOutput Green "Using subscription: $SUBSCRIPTION_ID"

# Create resource group if it doesn't exist
Write-Output ""
Write-ColorOutput Yellow "Step 1: Ensuring resource group exists..."
az group create --name $RESOURCE_GROUP --location $LOCATION --output none
Write-ColorOutput Green "✓ Resource group ready"

# Deploy infrastructure
Write-Output ""
Write-ColorOutput Yellow "Step 2: Deploying infrastructure with Bicep..."
Push-Location deploy

az deployment group create `
  --resource-group $RESOURCE_GROUP `
  --template-file function-app.bicep `
  --parameters `
    functionAppName=$FUNCTION_APP_NAME `
    appServicePlanName=$APP_SERVICE_PLAN_NAME `
    functionStorageAccountName=$FUNCTION_STORAGE_NAME `
    appInsightsName=$APP_INSIGHTS_NAME `
    dataStorageAccountName=$DATA_STORAGE_NAME `
    dataStorageContainerName=$DATA_CONTAINER_NAME `
    dataStorageResourceGroup=$DATA_STORAGE_RG `
    searchServiceName=$SEARCH_SERVICE_NAME `
    searchIndexName=$SEARCH_INDEX_NAME `
    openAiServiceName=$OPENAI_SERVICE_NAME `
    documentIntelligenceServiceName=$DOC_INTEL_SERVICE_NAME `
    subscriptionId=$SUBSCRIPTION_ID `
    location=$LOCATION `
  --output table

Write-ColorOutput Green "✓ Infrastructure deployed"

# Wait for role assignments to propagate
Write-Output ""
Write-ColorOutput Yellow "Step 3: Waiting for role assignments to propagate (30 seconds)..."
Start-Sleep -Seconds 30
Write-ColorOutput Green "✓ Role assignments ready"

# Deploy function code
Write-Output ""
Write-ColorOutput Yellow "Step 4: Deploying function code..."
Pop-Location

func azure functionapp publish $FUNCTION_APP_NAME --python

Write-ColorOutput Green "✓ Function code deployed"

# Get managed identity principal ID
$PRINCIPAL_ID = az functionapp identity show `
  --name $FUNCTION_APP_NAME `
  --resource-group $RESOURCE_GROUP `
  --query principalId -o tsv

Write-Output ""
Write-ColorOutput Green "================================================"
Write-ColorOutput Green "Deployment Completed Successfully!"
Write-ColorOutput Green "================================================"
Write-Output ""
Write-ColorOutput Green "Function App: $FUNCTION_APP_NAME"
Write-ColorOutput Green "Managed Identity Principal ID: $PRINCIPAL_ID"
Write-ColorOutput Green "Resource Group: $RESOURCE_GROUP"
Write-Output ""
Write-ColorOutput Yellow "Next Steps:"
Write-Output "1. Verify role assignments:"
Write-Output "   az role assignment list --assignee $PRINCIPAL_ID --all --output table"
Write-Output ""
Write-Output "2. Monitor function execution:"
Write-Output "   func azure functionapp logstream $FUNCTION_APP_NAME"
Write-Output ""
Write-Output "3. Manually trigger the function (optional):"
Write-Output "   az functionapp function invoke --name $FUNCTION_APP_NAME --resource-group $RESOURCE_GROUP --function-name DataIngestionFunction"
Write-Output ""
Write-ColorOutput Green "Function URL:"
$FUNCTION_URL = az functionapp show --name $FUNCTION_APP_NAME --resource-group $RESOURCE_GROUP --query defaultHostName -o tsv
Write-Output "https://$FUNCTION_URL"
Write-Output ""

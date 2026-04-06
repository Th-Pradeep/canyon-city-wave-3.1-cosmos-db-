#!/bin/bash

# Deploy Azure Function App for Data Ingestion with Managed Identity
# This script deploys the infrastructure and function code

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}Azure Function App Deployment Script${NC}"
echo -e "${GREEN}Data Ingestion with Managed Identity${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""

# Check if Azure CLI is installed
if ! command -v az &> /dev/null; then
    echo -e "${RED}Error: Azure CLI is not installed${NC}"
    echo "Please install it from: https://learn.microsoft.com/cli/azure/install-azure-cli"
    exit 1
fi

# Check if Azure Functions Core Tools is installed
if ! command -v func &> /dev/null; then
    echo -e "${RED}Error: Azure Functions Core Tools is not installed${NC}"
    echo "Please install it from: https://learn.microsoft.com/azure/azure-functions/functions-run-local"
    exit 1
fi

# Prompt for deployment parameters
echo -e "${YELLOW}Please provide deployment parameters:${NC}"
echo ""

read -p "Resource Group Name: " RESOURCE_GROUP
read -p "Location (default: eastus): " LOCATION
LOCATION=${LOCATION:-eastus}

read -p "Function App Name: " FUNCTION_APP_NAME
read -p "App Service Plan Name (default: asp-$FUNCTION_APP_NAME): " APP_SERVICE_PLAN_NAME
APP_SERVICE_PLAN_NAME=${APP_SERVICE_PLAN_NAME:-asp-$FUNCTION_APP_NAME}

# Generate unique storage account name
RANDOM_SUFFIX=$(openssl rand -hex 3)
DEFAULT_FUNC_STORAGE="stfunc${RANDOM_SUFFIX}"
read -p "Function Storage Account Name (default: $DEFAULT_FUNC_STORAGE): " FUNCTION_STORAGE_NAME
FUNCTION_STORAGE_NAME=${FUNCTION_STORAGE_NAME:-$DEFAULT_FUNC_STORAGE}

read -p "App Insights Name (default: appi-$FUNCTION_APP_NAME): " APP_INSIGHTS_NAME
APP_INSIGHTS_NAME=${APP_INSIGHTS_NAME:-appi-$FUNCTION_APP_NAME}

echo ""
echo -e "${YELLOW}Existing Azure Resources:${NC}"
read -p "Data Storage Account Name: " DATA_STORAGE_NAME
read -p "Data Storage Container Name: " DATA_CONTAINER_NAME
read -p "Data Storage Resource Group (default: $RESOURCE_GROUP): " DATA_STORAGE_RG
DATA_STORAGE_RG=${DATA_STORAGE_RG:-$RESOURCE_GROUP}

read -p "Search Service Name: " SEARCH_SERVICE_NAME
read -p "Search Index Name: " SEARCH_INDEX_NAME
read -p "OpenAI Service Name: " OPENAI_SERVICE_NAME
read -p "Document Intelligence Service Name: " DOC_INTEL_SERVICE_NAME

echo ""
echo -e "${GREEN}Deployment Configuration:${NC}"
echo "Resource Group: $RESOURCE_GROUP"
echo "Location: $LOCATION"
echo "Function App: $FUNCTION_APP_NAME"
echo "Data Storage: $DATA_STORAGE_NAME/$DATA_CONTAINER_NAME"
echo "Search Service: $SEARCH_SERVICE_NAME"
echo ""

read -p "Proceed with deployment? (yes/no): " CONFIRM
if [[ $CONFIRM != "yes" ]]; then
    echo "Deployment cancelled"
    exit 0
fi

# Get subscription ID
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
echo ""
echo -e "${GREEN}Using subscription: $SUBSCRIPTION_ID${NC}"

# Create resource group if it doesn't exist
echo ""
echo -e "${YELLOW}Step 1: Ensuring resource group exists...${NC}"
az group create --name $RESOURCE_GROUP --location $LOCATION --output none
echo -e "${GREEN}✓ Resource group ready${NC}"

# Deploy infrastructure
echo ""
echo -e "${YELLOW}Step 2: Deploying infrastructure with Bicep...${NC}"
cd deploy

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
    dataStorageResourceGroup=$DATA_STORAGE_RG \
    searchServiceName=$SEARCH_SERVICE_NAME \
    searchIndexName=$SEARCH_INDEX_NAME \
    openAiServiceName=$OPENAI_SERVICE_NAME \
    documentIntelligenceServiceName=$DOC_INTEL_SERVICE_NAME \
    subscriptionId=$SUBSCRIPTION_ID \
    location=$LOCATION \
  --output table

echo -e "${GREEN}✓ Infrastructure deployed${NC}"

# Wait for role assignments to propagate
echo ""
echo -e "${YELLOW}Step 3: Waiting for role assignments to propagate (30 seconds)...${NC}"
sleep 30
echo -e "${GREEN}✓ Role assignments ready${NC}"

# Deploy function code
echo ""
echo -e "${YELLOW}Step 4: Deploying function code...${NC}"
cd ..

func azure functionapp publish $FUNCTION_APP_NAME --python

echo -e "${GREEN}✓ Function code deployed${NC}"

# Get managed identity principal ID
PRINCIPAL_ID=$(az functionapp identity show \
  --name $FUNCTION_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query principalId -o tsv)

echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}Deployment Completed Successfully!${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "${GREEN}Function App:${NC} $FUNCTION_APP_NAME"
echo -e "${GREEN}Managed Identity Principal ID:${NC} $PRINCIPAL_ID"
echo -e "${GREEN}Resource Group:${NC} $RESOURCE_GROUP"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "1. Verify role assignments:"
echo "   az role assignment list --assignee $PRINCIPAL_ID --all --output table"
echo ""
echo "2. Monitor function execution:"
echo "   func azure functionapp logstream $FUNCTION_APP_NAME"
echo ""
echo "3. Manually trigger the function (optional):"
echo "   az functionapp function invoke --name $FUNCTION_APP_NAME --resource-group $RESOURCE_GROUP --function-name DataIngestionFunction"
echo ""
echo -e "${GREEN}Function URL:${NC}"
FUNCTION_URL=$(az functionapp show --name $FUNCTION_APP_NAME --resource-group $RESOURCE_GROUP --query defaultHostName -o tsv)
echo "https://$FUNCTION_URL"
echo ""

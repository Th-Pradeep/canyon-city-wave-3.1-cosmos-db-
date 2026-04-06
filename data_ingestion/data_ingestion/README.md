# Azure Function App - Data Ingestion

This Azure Function App monitors Azure Blob Storage for new or updated documents and automatically ingests them into Azure AI Search using managed identity for secure, keyless authentication.

## 🔐 Security Features

### Managed Identity
The Function App uses **system-assigned managed identity** to access Azure resources without storing any credentials.

### Role Assignments
The following Azure RBAC roles are automatically assigned to the Function App's managed identity:

| Resource | Role | Purpose |
|----------|------|---------|
| **Storage Account** | Storage Blob Data Contributor | Read and write access to blob containers |
| **AI Search Service** | Search Index Data Contributor | Create, update, and delete search documents |
| **Azure OpenAI** | Cognitive Services OpenAI User | Access embeddings and chat models |
| **Document Intelligence** | Cognitive Services User | Parse documents (PDF, DOCX, etc.) |

## 📋 Prerequisites

1. **Azure Subscription** with the following resources:
   - Azure Storage Account with a container for documents
   - Azure AI Search Service with an index
   - Azure OpenAI Service with deployed embeddings model (e.g., text-embedding-ada-002)
   - Azure Document Intelligence Service
   - Application Insights (optional but recommended)

2. **Development Tools**:
   - Azure Functions Core Tools 4.x
   - Python 3.10 or 3.11
   - Azure CLI

## 🚀 Quick Start

### 1. Local Development

#### Install Dependencies
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

#### Configure Local Settings
Copy and update `local.settings.json` with your Azure resource names:

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "AZURE_SUBSCRIPTION_ID": "your-subscription-id",
    "AZURE_STORAGE_ACCOUNT": "your-storage-account",
    "AZURE_STORAGE_CONTAINER": "documents",
    "AZURE_SEARCH_SERVICE": "your-search-service",
    "AZURE_SEARCH_INDEX": "documents-index",
    "AZURE_OPENAI_SERVICE": "your-openai-service",
    ...
  }
}
```

#### Run Locally
```bash
func start
```

### 2. Deploy to Azure

#### Option A: Deploy Infrastructure + Code

```bash
# 1. Deploy infrastructure with Bicep
cd deploy
az deployment group create \
  --resource-group <your-rg> \
  --template-file function-app.bicep \
  --parameters @parameters.json

# 2. Deploy function code
cd ..
func azure functionapp publish <function-app-name>
```

#### Option B: Quick Deploy (Code Only)

If infrastructure already exists:

```bash
func azure functionapp publish <function-app-name>
```

## 📁 Project Structure

```
data_ingestion/
├── DataIngestionFunction/        # Function definition
│   ├── __init__.py              # Function entry point
│   └── function.json            # Timer trigger configuration
├── prepdocslib/                 # Data processing library
│   ├── blobmanager.py          # Blob storage operations
│   ├── fileprocessor.py        # File parsing
│   ├── searchmanager.py        # Search index operations
│   └── ...
├── data_ingestion_function_app.py  # Main ingestion logic
├── requirements.txt             # Python dependencies
├── host.json                    # Function app configuration
├── local.settings.json          # Local environment variables
├── deploy/                      # Infrastructure as Code
│   ├── function-app.bicep      # Bicep template
│   └── README.md               # Deployment guide
└── README.md                    # This file
```

## ⚙️ Configuration

### Timer Schedule

The function runs on a timer schedule defined in `DataIngestionFunction/function.json`:

```json
{
  "schedule": "0 */30 * * * *"  // Every 30 minutes
}
```

**Common Schedules:**
- Every hour: `0 0 * * * *`
- Every 6 hours: `0 0 */6 * * *`
- Daily at 2 AM: `0 0 2 * * *`
- Weekly on Monday at 3 AM: `0 0 3 * * 1`

See [NCRONTAB expressions](https://learn.microsoft.com/azure/azure-functions/functions-bindings-timer?tabs=python-v2%2Cin-process&pivots=programming-language-python#ncrontab-expressions) for more details.

### Environment Variables

Key application settings:

| Setting | Description | Default |
|---------|-------------|---------|
| `INGESTION_LOOKBACK_HOURS` | Hours to look back for new files | `24` |
| `USE_VECTORS` | Enable vector embeddings | `true` |
| `USE_MULTIMODAL` | Process images with GPT-4V | `false` |
| `FORCE_REINDEX` | Force index recreation | `false` |
| `VERBOSE_LOGGING` | Enable debug logging | `false` |

**Update settings:**
```bash
az functionapp config appsettings set \
  --name <function-app-name> \
  --resource-group <resource-group> \
  --settings \
    INGESTION_LOOKBACK_HOURS=48 \
    VERBOSE_LOGGING=true
```

## 🔍 Monitoring

### View Logs

```bash
# Stream live logs
func azure functionapp logstream <function-app-name>

# Or using Azure CLI
az webapp log tail \
  --name <function-app-name> \
  --resource-group <resource-group>
```

### Application Insights

Query logs in Application Insights:

```kusto
traces
| where operation_Name == "DataIngestionFunction"
| where timestamp > ago(1h)
| order by timestamp desc
| project timestamp, message, severityLevel
```

### Check Function Status

```bash
az functionapp function show \
  --name <function-app-name> \
  --resource-group <resource-group> \
  --function-name DataIngestionFunction
```

## 🧪 Testing

### Manual Trigger

```bash
# Trigger the function immediately (don't wait for timer)
az functionapp function invoke \
  --name <function-app-name> \
  --resource-group <resource-group> \
  --function-name DataIngestionFunction
```

### Test with Sample Files

1. Upload files to the monitored blob container:
```bash
az storage blob upload \
  --account-name <storage-account> \
  --container-name documents \
  --file sample.pdf \
  --name sample.pdf \
  --auth-mode login
```

2. Check logs to see processing:
```bash
func azure functionapp logstream <function-app-name>
```

## 🔧 Troubleshooting

### Verify Managed Identity

```bash
# Check if managed identity is enabled
az functionapp identity show \
  --name <function-app-name> \
  --resource-group <resource-group>
```

### Verify Role Assignments

```bash
# Get principal ID
PRINCIPAL_ID=$(az functionapp identity show \
  --name <function-app-name> \
  --resource-group <resource-group> \
  --query principalId -o tsv)

# List all role assignments
az role assignment list \
  --assignee $PRINCIPAL_ID \
  --all \
  --output table
```

### Common Issues

#### "Access Denied" on Storage Account
- Verify the Function App has **Storage Blob Data Contributor** role
- Role propagation can take up to 5 minutes

#### "Search Index Not Found"
- Ensure the search index exists
- Check the `AZURE_SEARCH_INDEX` setting matches the actual index name

#### "OpenAI Embedding Failed"
- Verify the embeddings model is deployed
- Check `AZURE_OPENAI_EMB_DEPLOYMENT` matches the deployment name
- Ensure Function App has **Cognitive Services OpenAI User** role

#### Function Not Triggering
- Check the timer schedule in `function.json`
- View function execution history in Application Insights
- Verify the Function App is running (not stopped)

## 📚 How It Works

1. **Timer Triggers**: Function runs on schedule (default: every 30 minutes)
2. **Blob Monitoring**: Scans configured container for new/updated/deleted files
3. **State Tracking**: Tracks last sync time in `/tmp/last_sync.json`
4. **Document Processing**:
   - Downloads new/updated files
   - Parses documents using Document Intelligence
   - Generates embeddings using Azure OpenAI
   - Chunks text for optimal retrieval
5. **Index Updates**:
   - Adds/updates documents in Search index
   - Removes deleted documents
6. **Logging**: Records all operations in Application Insights

## 🔒 Security Best Practices

✅ **Managed Identity** - No credentials in code or configuration  
✅ **RBAC Roles** - Least privilege access to resources  
✅ **HTTPS Only** - All communication encrypted  
✅ **TLS 1.2+** - Modern encryption standards  
✅ **Key Vault** - Store secrets (if API keys needed)  
✅ **Private Endpoints** - Optional network isolation  

## 📖 Additional Resources

- [Azure Functions Python Developer Guide](https://learn.microsoft.com/azure/azure-functions/functions-reference-python)
- [Managed Identity Overview](https://learn.microsoft.com/azure/active-directory/managed-identities-azure-resources/overview)
- [Azure RBAC Roles](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles)
- [Azure AI Search](https://learn.microsoft.com/azure/search/)
- [Azure OpenAI Service](https://learn.microsoft.com/azure/ai-services/openai/)

## 📝 License

See the main repository for license information.

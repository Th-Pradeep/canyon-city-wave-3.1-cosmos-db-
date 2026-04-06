# Quick Start Guide

## 🚀 Deploy in 5 Minutes

### Prerequisites
- Azure subscription
- Existing Azure resources (Storage Account, AI Search, OpenAI, Document Intelligence)
- Azure CLI and Azure Functions Core Tools installed

### Option 1: Automated Deployment (Recommended)

**Windows (PowerShell):**
```powershell
cd deploy
.\deploy.ps1
```

**Linux/macOS (Bash):**
```bash
cd deploy
chmod +x deploy.sh
./deploy.sh
```

The script will:
1. ✅ Create resource group
2. ✅ Deploy Function App with managed identity
3. ✅ Assign all required RBAC roles
4. ✅ Deploy function code
5. ✅ Verify deployment

### Option 2: Manual Deployment

#### Step 1: Update Parameters
Copy and edit the parameters file:
```bash
cd deploy
cp parameters.example.json parameters.json
# Edit parameters.json with your resource names
```

#### Step 2: Deploy Infrastructure
```bash
az deployment group create \
  --resource-group <your-rg> \
  --template-file function-app.bicep \
  --parameters @parameters.json
```

#### Step 3: Deploy Code
```bash
cd ..
func azure functionapp publish <function-app-name>
```

### Verify Deployment

**Check role assignments:**
```powershell
cd deploy
.\validate-roles.ps1 -FunctionAppName <name> -ResourceGroup <rg>
```

**Stream logs:**
```bash
func azure functionapp logstream <function-app-name>
```

**Manual trigger:**
```bash
az functionapp function invoke \
  --name <function-app-name> \
  --resource-group <rg> \
  --function-name DataIngestionFunction
```

## 🔧 Configuration

### Adjust Timer Schedule
Edit `DataIngestionFunction/function.json`:
```json
{
  "schedule": "0 0 * * * *"  // Every hour
}
```

### Update Settings
```bash
az functionapp config appsettings set \
  --name <function-app-name> \
  --resource-group <rg> \
  --settings INGESTION_LOOKBACK_HOURS=48
```

## 📊 Monitoring

View in Azure Portal:
- **Function App** → Logs
- **Application Insights** → Live Metrics
- **Storage Account** → Monitor container

## ❓ Troubleshooting

**Access Denied Error?**
- Wait 5 minutes for role propagation
- Verify roles: `.\validate-roles.ps1`

**Function Not Running?**
- Check schedule in `function.json`
- Verify Function App is started
- Check Application Insights logs

**Need Help?**
See full [README.md](../README.md) for detailed documentation.

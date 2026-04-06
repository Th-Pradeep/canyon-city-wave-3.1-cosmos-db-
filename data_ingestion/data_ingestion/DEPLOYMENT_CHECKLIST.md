# Pre-Deployment Checklist

Before deploying the Function App, ensure you have the following:

## ✅ Azure Resources (Must Exist)

### Required Resources
- [ ] **Azure Subscription** with appropriate permissions
- [ ] **Resource Group** (or permissions to create one)
- [ ] **Storage Account** with a container for source documents
- [ ] **Azure AI Search Service** with or without an index (can be auto-created)
- [ ] **Azure OpenAI Service** with deployed embeddings model
  - Model: `text-embedding-ada-002` or similar
  - Deployment name recorded
- [ ] **Document Intelligence Service** (formerly Form Recognizer)

### Resource Information to Collect
- [ ] Storage Account name: ________________
- [ ] Storage Container name: ________________
- [ ] Storage Resource Group: ________________
- [ ] Search Service name: ________________
- [ ] Search Index name: ________________
- [ ] OpenAI Service name: ________________
- [ ] OpenAI Embeddings deployment: ________________
- [ ] Document Intelligence name: ________________
- [ ] Subscription ID: ________________

## ✅ Development Tools

### Required Software
- [ ] **Azure CLI** installed and logged in
  ```bash
  az --version
  az login
  ```

- [ ] **Azure Functions Core Tools** v4.x
  ```bash
  func --version
  ```

- [ ] **Python** 3.10 or 3.11
  ```bash
  python --version
  ```

### Optional but Recommended
- [ ] **Git** for version control
- [ ] **VS Code** with Azure Functions extension
- [ ] **PowerShell** 7+ (Windows) or **Bash** (Linux/macOS)

## ✅ Permissions

### Azure Permissions Required
- [ ] **Contributor** or **Owner** role on subscription or resource group
- [ ] Permission to **create role assignments**
- [ ] Permission to **create managed identities**

### Verify Permissions
```bash
# Check your current role
az role assignment list --assignee $(az account show --query user.name -o tsv) --all

# Verify you can create role assignments
az role assignment create --help
```

## ✅ Network Access

- [ ] Outbound HTTPS (443) to:
  - Azure Storage (*.blob.core.windows.net)
  - Azure Search (*.search.windows.net)
  - Azure OpenAI (*.openai.azure.com)
  - Azure Document Intelligence (*.cognitiveservices.azure.com)

## ✅ Configuration Decisions

### Function App Settings
- [ ] Desired **Function App name**: ________________
- [ ] Preferred **Azure region**: ________________
- [ ] **Timer schedule** (default: every 30 minutes)
  - Your schedule: ________________

### Ingestion Settings
- [ ] **Lookback hours** for file detection (default: 24)
- [ ] Enable **vector embeddings**? (recommended: yes)
- [ ] Enable **multimodal** (images with GPT-4V)? (optional)
- [ ] Enable **verbose logging**? (recommended for initial testing)

## ✅ Deployment Method

Choose your deployment approach:

### Option A: Automated Script (Recommended)
- [ ] Using Windows? Use `deploy.ps1`
- [ ] Using Linux/macOS? Use `deploy.sh`

### Option B: Manual Deployment
- [ ] Created `deploy/parameters.json` from example
- [ ] Reviewed and updated all parameter values
- [ ] Ready to run `az deployment group create`

### Option C: CI/CD Pipeline
- [ ] Set up GitHub Actions or Azure DevOps
- [ ] Configured service principal
- [ ] Added secrets/variables

## ✅ Post-Deployment Verification

After deployment, you should:
- [ ] Run `validate-roles.ps1` to verify role assignments
- [ ] Upload a test document to storage container
- [ ] Trigger the function manually to test
- [ ] Check Application Insights for execution logs
- [ ] Verify document appears in search index
- [ ] Set up alerts in Application Insights

## 🚀 Ready to Deploy?

### Quick Command Reference

**Automated Deployment (Windows):**
```powershell
cd deploy
.\deploy.ps1
```

**Automated Deployment (Linux/macOS):**
```bash
cd deploy
chmod +x deploy.sh
./deploy.sh
```

**Validate After Deployment:**
```powershell
cd deploy
.\validate-roles.ps1 -FunctionAppName <name> -ResourceGroup <rg>
```

**Manual Trigger:**
```bash
az functionapp function invoke \
  --name <function-app-name> \
  --resource-group <resource-group> \
  --function-name DataIngestionFunction
```

**Stream Logs:**
```bash
func azure functionapp logstream <function-app-name>
```

## 📚 Documentation

- **Setup Summary**: [SETUP_SUMMARY.md](SETUP_SUMMARY.md)
- **Quick Start**: [QUICKSTART.md](QUICKSTART.md)
- **Full README**: [README.md](README.md)
- **Deployment Guide**: [deploy/README.md](deploy/README.md)

## ❓ Questions?

If you're unsure about any of these items, refer to:
1. [Azure Functions Documentation](https://learn.microsoft.com/azure/azure-functions/)
2. [Managed Identity Documentation](https://learn.microsoft.com/azure/active-directory/managed-identities-azure-resources/)
3. [Azure RBAC Documentation](https://learn.microsoft.com/azure/role-based-access-control/)

---

**Once all checkboxes are complete, you're ready to deploy!** 🎉

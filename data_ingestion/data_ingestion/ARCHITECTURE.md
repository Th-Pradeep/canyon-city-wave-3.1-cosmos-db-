# Architecture Overview

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Azure Function App (Python 3.11)                      │
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │                    DataIngestionFunction                            │    │
│  │                   (Timer Trigger: Every 30 min)                    │    │
│  │                                                                     │    │
│  │  1. Monitor blob storage for changes                              │    │
│  │  2. Download new/updated files                                     │    │
│  │  3. Parse documents (PDF, DOCX, etc.)                             │    │
│  │  4. Generate embeddings                                            │    │
│  │  5. Chunk and index content                                        │    │
│  │  6. Remove deleted documents                                       │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                               │
│                    System-Assigned Managed Identity                          │
│                    (No credentials stored!)                                  │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                │ Authenticated Access via RBAC
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       ▼                       ▼
┌──────────────────┐    ┌──────────────────┐   ┌──────────────────┐
│  Storage Account │    │  Azure AI Search │   │  Azure OpenAI    │
│                  │    │                  │   │                  │
│  Role:           │    │  Role:           │   │  Role:           │
│  Storage Blob    │    │  Search Index    │   │  Cognitive Svcs  │
│  Data Contributor│    │  Data Contributor│   │  OpenAI User     │
│                  │    │                  │   │                  │
│  ┌────────────┐  │    │  ┌────────────┐  │   │  Embeddings:     │
│  │ Container: │  │    │  │   Index    │  │   │  - ada-002      │
│  │ documents  │  │    │  │            │  │   │                  │
│  │            │  │    │  │ [chunks]   │  │   │  Chat (optional):│
│  │ - file1.pdf│  │    │  │            │  │   │  - gpt-4        │
│  │ - file2.docx│ │    │  └────────────┘  │   └──────────────────┘
│  └────────────┘  │    │                  │
└──────────────────┘    └──────────────────┘
                                │
                                │
                        ┌───────▼──────────────┐
                        │ Document Intelligence│
                        │                      │
                        │  Role:               │
                        │  Cognitive Services  │
                        │  User                │
                        │                      │
                        │  Parse:              │
                        │  - PDF               │
                        │  - DOCX              │
                        │  - Images            │
                        └──────────────────────┘
```

## Data Flow

```
┌─────────────┐
│   1. Timer  │  Every 30 minutes (configurable)
│   Triggers  │
└──────┬──────┘
       │
       ▼
┌──────────────────────────────────────────────────┐
│   2. Monitor Storage Container                   │
│   - List all blobs                               │
│   - Compare with last sync state                 │
│   - Identify new, updated, and deleted files     │
└──────┬───────────────────────────────────────────┘
       │
       ├─────────────────┬──────────────────┐
       ▼                 ▼                  ▼
┌─────────────┐  ┌──────────────┐  ┌──────────────┐
│ New Files   │  │Updated Files │  │Deleted Files │
└──────┬──────┘  └──────┬───────┘  └──────┬───────┘
       │                │                  │
       └────────┬───────┘                  │
                ▼                          ▼
┌────────────────────────────────┐  ┌─────────────────┐
│   3. Download & Parse          │  │  8. Remove from │
│   - Download blob              │  │     Index       │
│   - Send to Doc Intelligence   │  └─────────────────┘
│   - Extract text & structure   │
└────────┬───────────────────────┘
         │
         ▼
┌────────────────────────────────┐
│   4. Generate Embeddings       │
│   - Call Azure OpenAI          │
│   - Create vector embeddings   │
└────────┬───────────────────────┘
         │
         ▼
┌────────────────────────────────┐
│   5. Chunk Content             │
│   - Split into searchable chunks│
│   - Preserve context           │
└────────┬───────────────────────┘
         │
         ▼
┌────────────────────────────────┐
│   6. Enrich Metadata           │
│   - Add source file info       │
│   - Add timestamps             │
│   - Add embeddings             │
└────────┬───────────────────────┘
         │
         ▼
┌────────────────────────────────┐
│   7. Index in Search           │
│   - Upload to AI Search        │
│   - Make searchable            │
└────────────────────────────────┘
```

## Security Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    Function App                               │
│  ┌────────────────────────────────────────────────────┐      │
│  │      System-Assigned Managed Identity              │      │
│  │                                                     │      │
│  │  • Automatically created by Azure                  │      │
│  │  • Unique service principal                        │      │
│  │  • No passwords or keys to manage                  │      │
│  │  • Tokens auto-refreshed by Azure                  │      │
│  └────────────────────────┬───────────────────────────┘      │
└───────────────────────────┼──────────────────────────────────┘
                            │
                            │ Azure Active Directory
                            │ Authentication & Authorization
                            │
            ┌───────────────┴───────────────┐
            │                               │
            ▼                               ▼
    ┌──────────────┐              ┌──────────────────┐
    │   Azure      │              │   Role           │
    │   Resource   │              │   Assignment     │
    │              │              │                  │
    │   Checks:    │              │   Links:         │
    │   "Does this │◄─────────────┤   • Identity     │
    │   identity   │              │   • Role         │
    │   have       │              │   • Resource     │
    │   permission?"│             │                  │
    └──────┬───────┘              └──────────────────┘
           │
           │ ✅ Permission Granted
           ▼
    ┌──────────────┐
    │   Access     │
    │   Resource   │
    └──────────────┘
```

## Role-Based Access Control (RBAC)

```
Function App Managed Identity
            │
            ├── Storage Blob Data Contributor
            │   └── Storage Account: <your-storage>
            │       └── Container: documents
            │           ├── Read blobs
            │           ├── Write blobs (temp storage)
            │           └── List blobs
            │
            ├── Search Index Data Contributor
            │   └── Search Service: <your-search>
            │       └── Index: documents-index
            │           ├── Create documents
            │           ├── Update documents
            │           ├── Delete documents
            │           └── Query (for deletion)
            │
            ├── Cognitive Services OpenAI User
            │   └── OpenAI Service: <your-openai>
            │       ├── Generate embeddings
            │       └── Chat completions (optional)
            │
            └── Cognitive Services User
                └── Document Intelligence: <your-doc-intel>
                    ├── Analyze documents
                    ├── Extract text
                    └── Parse structure
```

## Monitoring & Logging

```
┌──────────────────────────────────────────────────────────┐
│                   Function App                            │
└────────────────────┬─────────────────────────────────────┘
                     │
                     │ Telemetry
                     ▼
            ┌─────────────────────┐
            │ Application Insights │
            │                      │
            │  Captures:           │
            │  • Execution logs    │
            │  • Performance      │
            │  • Errors           │
            │  • Dependencies     │
            │  • Custom events    │
            └──────────┬───────────┘
                       │
                       │ Query & Visualize
                       ▼
            ┌──────────────────────┐
            │  Azure Portal        │
            │  • Live Metrics      │
            │  • Log Analytics     │
            │  • Alerts            │
            │  • Dashboards        │
            └──────────────────────┘
```

## Deployment Process

```
Developer Workstation
        │
        │ 1. Run deploy script
        ▼
┌────────────────────┐
│   Azure CLI        │
│   az deployment... │
└────────┬───────────┘
         │
         │ 2. Deploy Bicep template
         ▼
┌──────────────────────────────────────────┐
│   Azure Resource Manager                 │
│                                          │
│   Creates:                               │
│   • Resource Group                       │
│   • App Service Plan                     │
│   • Function App                         │
│   • Storage Account (for function)       │
│   • Application Insights                 │
│   • Managed Identity                     │
│   • Role Assignments (4 roles)           │
└────────┬─────────────────────────────────┘
         │
         │ 3. Resources ready
         ▼
┌────────────────────┐
│   Function App     │
│   (empty, waiting) │
└────────┬───────────┘
         │
         │ 4. Deploy code (func azure functionapp publish)
         ▼
┌────────────────────┐
│   Function App     │
│   (code deployed)  │
│   ✅ Ready to run   │
└────────────────────┘
```

## State Management

```
Function Execution
        │
        ├── Read State
        │   └── /tmp/last_sync.json
        │       {
        │         "last_sync_time": "2024-01-28T10:00:00Z",
        │         "tracked_blobs": ["file1.pdf", "file2.docx"]
        │       }
        │
        ├── Process Changes
        │   ├── New files (not in tracked_blobs)
        │   ├── Updated files (modified > last_sync_time)
        │   └── Deleted files (in tracked_blobs but not in container)
        │
        └── Update State
            └── /tmp/last_sync.json
                {
                  "last_sync_time": "2024-01-28T10:30:00Z",
                  "tracked_blobs": ["file1.pdf", "file2.docx", "file3.pdf"]
                }
```

---

## Key Benefits

✅ **No Credentials** - Managed identity eliminates secrets  
✅ **Automatic Auth** - Azure handles token acquisition  
✅ **Least Privilege** - Only required roles assigned  
✅ **Audit Trail** - All access logged  
✅ **Scalable** - Elastic Premium plan auto-scales  
✅ **Monitored** - Full observability with App Insights  
✅ **Automated** - Timer-based, no manual intervention  
✅ **Resilient** - Handles failures gracefully  

---

*This architecture follows Azure best practices for serverless data processing with secure, managed identity-based access.*

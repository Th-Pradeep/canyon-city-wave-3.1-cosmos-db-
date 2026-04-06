# Validate Azure Function App Role Assignments
# This script checks if all required role assignments are correctly configured

param(
    [Parameter(Mandatory=$true)]
    [string]$FunctionAppName,
    
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup
)

$ErrorActionPreference = "Stop"

# Colors for output
function Write-ColorOutput($ForegroundColor, $Message) {
    $fc = $host.UI.RawUI.ForegroundColor
    $host.UI.RawUI.ForegroundColor = $ForegroundColor
    Write-Output $Message
    $host.UI.RawUI.ForegroundColor = $fc
}

Write-ColorOutput Green "================================================"
Write-ColorOutput Green "Azure Function App Role Assignment Validation"
Write-ColorOutput Green "================================================"
Write-Output ""

# Get Function App Managed Identity
Write-Output "Checking Function App managed identity..."
try {
    $identity = az functionapp identity show `
        --name $FunctionAppName `
        --resource-group $ResourceGroup `
        --query principalId -o tsv
    
    if ([string]::IsNullOrWhiteSpace($identity)) {
        Write-ColorOutput Red "✗ No managed identity found!"
        Write-Output "Please enable system-assigned managed identity for the Function App"
        exit 1
    }
    
    Write-ColorOutput Green "✓ Managed Identity Principal ID: $identity"
} catch {
    Write-ColorOutput Red "✗ Failed to get managed identity: $_"
    exit 1
}

Write-Output ""

# Get all role assignments
Write-Output "Retrieving role assignments..."
$roleAssignments = az role assignment list --assignee $identity --all --output json | ConvertFrom-Json

if ($roleAssignments.Count -eq 0) {
    Write-ColorOutput Red "✗ No role assignments found!"
    exit 1
}

Write-ColorOutput Green "✓ Found $($roleAssignments.Count) role assignment(s)"
Write-Output ""

# Required roles with their IDs
$requiredRoles = @{
    "Storage Blob Data Contributor" = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"
    "Search Index Data Contributor" = "8ebe5a00-799e-43f5-93ac-243d3dce84a7"
    "Cognitive Services OpenAI User" = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
    "Cognitive Services User" = "a97b65f3-24c7-4388-baec-2e87135dc908"
}

Write-ColorOutput Yellow "Validating Required Role Assignments:"
Write-Output ""

$allValid = $true

foreach ($roleName in $requiredRoles.Keys) {
    $roleId = $requiredRoles[$roleName]
    $found = $false
    
    foreach ($assignment in $roleAssignments) {
        # Extract role definition ID from the full resource ID
        if ($assignment.roleDefinitionId -like "*$roleId") {
            $found = $true
            $scope = $assignment.scope
            
            # Extract resource type from scope
            $resourceType = ""
            if ($scope -like "*/Microsoft.Storage/storageAccounts/*") {
                $resourceType = "Storage Account"
            } elseif ($scope -like "*/Microsoft.Search/searchServices/*") {
                $resourceType = "Search Service"
            } elseif ($scope -like "*/Microsoft.CognitiveServices/accounts/*") {
                $resourceType = "Cognitive Services"
            } else {
                $resourceType = "Subscription/ResourceGroup"
            }
            
            # Extract resource name from scope
            $resourceName = ($scope -split '/')[-1]
            
            Write-ColorOutput Green "✓ $roleName"
            Write-Output "  Resource: $resourceName ($resourceType)"
            Write-Output "  Scope: $scope"
            break
        }
    }
    
    if (-not $found) {
        Write-ColorOutput Red "✗ $roleName - NOT FOUND"
        $allValid = $false
    }
    
    Write-Output ""
}

# Summary
Write-ColorOutput Green "================================================"
if ($allValid) {
    Write-ColorOutput Green "✓ All Required Role Assignments Valid!"
    Write-ColorOutput Green "================================================"
    Write-Output ""
    Write-Output "The Function App has all required permissions to:"
    Write-Output "  • Read/write blobs from Storage Account"
    Write-Output "  • Create/update documents in Search Index"
    Write-Output "  • Access Azure OpenAI embeddings and models"
    Write-Output "  • Use Document Intelligence service"
    Write-Output ""
    exit 0
} else {
    Write-ColorOutput Red "✗ Missing Required Role Assignments!"
    Write-ColorOutput Red "================================================"
    Write-Output ""
    Write-Output "Please assign the missing roles using Azure Portal or CLI"
    Write-Output "Example CLI command:"
    Write-Output "  az role assignment create \"
    Write-Output "    --assignee $identity \"
    Write-Output "    --role 'Storage Blob Data Contributor' \"
    Write-Output "    --scope /subscriptions/{sub-id}/resourceGroups/{rg}/providers/Microsoft.Storage/storageAccounts/{name}"
    Write-Output ""
    exit 1
}

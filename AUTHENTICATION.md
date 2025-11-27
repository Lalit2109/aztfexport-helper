# Authentication Guide

## Local Execution (Recommended)

This solution is designed to use your **Azure CLI credentials** from `az login`. No service principal or client ID/secret needed!

### Setup

1. **Login to Azure CLI:**
   ```bash
   az login
   ```

2. **Verify you're logged in:**
   ```bash
   az account show
   ```

3. **Set default subscription (optional):**
   ```bash
   az account set --subscription "your-subscription-id"
   ```

4. **Run the export:**
   ```bash
   python src/main.py
   ```

That's it! The code automatically uses your Azure CLI credentials.

### How It Works

- The code uses `DefaultAzureCredential()` which automatically tries multiple authentication methods in order:
  1. Environment variables (if set)
  2. Managed Identity (if running on Azure)
  3. **Azure CLI (`az login`)** ← This is what you'll use locally
  4. Azure PowerShell
  5. Azure Developer CLI

- `aztfexport` also uses Azure CLI credentials automatically when you run `az login`

### Verification

When you run the script, it will:
1. Check if Azure CLI is installed and logged in
2. Display your current Azure account information
3. Use those credentials for all operations

You'll see output like:
```
Verifying Azure authentication...
✓ Authenticated with Azure CLI
  Current account: Your Name (your@email.com)
  Subscription ID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

## Alternative: Service Principal (Optional)

If you prefer to use a service principal instead of Azure CLI:

1. **Create a service principal:**
   ```bash
   az ad sp create-for-rbac --name "terraform-export-sp" \
     --role "Reader" \
     --scopes /subscriptions/{subscription-id}
   ```

2. **Set environment variables:**
   ```bash
   export AZURE_CLIENT_ID="your-client-id"
   export AZURE_CLIENT_SECRET="your-client-secret"
   export AZURE_TENANT_ID="your-tenant-id"
   ```

3. **Run the export:**
   ```bash
   python src/main.py
   ```

The code will detect these environment variables and use them instead of Azure CLI.

## Azure DevOps Pipeline

For Azure DevOps pipelines, use a **Service Connection**:

1. Create an Azure Service Connection in Azure DevOps
2. Reference it in `azure-pipelines.yml`:
   ```yaml
   azureSubscription: 'Your-Service-Connection-Name'
   ```

The pipeline will use the service connection's managed identity or service principal.

## Troubleshooting

### "Not logged in to Azure CLI"
```bash
az login
az account show  # Verify
```

### "Azure CLI not found"
Install Azure CLI:
- macOS: `brew install azure-cli`
- Linux: Follow [official guide](https://docs.microsoft.com/cli/azure/install-azure-cli)
- Windows: Download from Microsoft

### Permission Errors
Ensure your account has at least **Reader** role on the subscriptions you want to export:
```bash
az role assignment list --assignee $(az account show --query user.name -o tsv) \
  --scope /subscriptions/{subscription-id}
```

### Multiple Subscriptions
If you have access to multiple subscriptions, the script will use the one set as default:
```bash
az account list --output table
az account set --subscription "subscription-id"
```

## Summary

✅ **For local execution:** Just use `az login` - no configuration needed!  
✅ **For Azure DevOps:** Use service connections  
✅ **Service Principal:** Optional, only if you prefer it over Azure CLI


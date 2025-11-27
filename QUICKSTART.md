# Quick Start Guide

## Prerequisites Setup

1. **Install Go** (for aztfexport):
   ```bash
   # macOS
   brew install go
   
   # Linux
   # Download from https://golang.org/dl/
   ```

2. **Install Python 3.10+**:
   ```bash
   python3 --version
   ```

3. **Install Azure CLI** (optional but recommended):
   ```bash
   # macOS
   brew install azure-cli
   
   # Or follow: https://docs.microsoft.com/cli/azure/install-azure-cli
   ```

## Initial Setup

1. **Run setup script:**
   ```bash
   ./scripts/setup.sh
   ```

2. **Configure subscriptions:**
   Edit `config/subscriptions.yaml` and add your 35 subscriptions:
   ```yaml
   subscriptions:
     - id: "subscription-id-1"
       name: "Production Subscription 1"
       environment: "prod"
       repo_name: "terraform-prod-sub-1"
       repo_url: "https://dev.azure.com/your-org/your-project/_git/terraform-prod-sub-1"
       export_enabled: true
   ```

3. **Authenticate with Azure CLI:**
   ```bash
   az login
   az account set --subscription "your-subscription-id"  # Optional: set default
   ```
   
   **Note:** The code automatically uses your Azure CLI credentials from `az login`.
   No need to configure service principal or client ID/secret!

## Local Testing

### Step 1: Export and Verify (Recommended First Step)

Export resources without pushing to git (default behavior):

```bash
# Make sure you're logged in
az login

# Run export (git push disabled by default)
python src/main.py
```

This exports to `./exports/` directory. Review the code before pushing.

### Step 2: Review Exported Code

```bash
# Check exports
ls -la exports/

# Review specific subscription
ls -la exports/production-subscription-1/

# Review specific resource group
cat exports/production-subscription-1/resource-group-1/main.tf
```

### Step 3: Enable Git Push (After Verification)

Once you've verified the exports, enable git push:

**Option 1: Edit config file**
```yaml
# Edit config/subscriptions.yaml
git:
  push_to_repos: true  # Change to true
```

**Option 2: Use environment variable**
```bash
export PUSH_TO_REPOS=true
export AZURE_DEVOPS_PAT=your-pat-token  # Only needed for pushing
python src/main.py
```

## Azure DevOps Setup

### 1. Create Repositories (Optional)

If repositories don't exist, create them:
```bash
export AZURE_DEVOPS_PAT=your-pat-token
python scripts/create_repos.py
```

### 2. Configure Pipeline

1. **Create Variable Group:**
   - Go to Azure DevOps → Pipelines → Library
   - Create variable group: `TerraformExport`
   - Add variable: `azureServiceConnection` = your service connection name

2. **Import Pipeline:**
   - Go to Pipelines → New Pipeline
   - Select your repository
   - Choose "Existing Azure Pipelines YAML file"
   - Select `azure-pipelines.yml`

3. **Grant Permissions:**
   - Pipeline → Settings → Permissions
   - Grant "Contribute" permission to all target repositories
   - Or use a PAT token with appropriate permissions

### 3. Run Pipeline

- Trigger manually or on commit to main branch
- Pipeline will export and push to all configured repositories

## Output Structure

```
exports/
├── production-subscription-1/
│   ├── resource-group-1/
│   │   ├── main.tf
│   │   ├── providers.tf
│   │   └── terraform.tfstate
│   ├── resource-group-2/
│   │   └── ...
│   └── .git/  (if PUSH_TO_REPOS=true)
├── development-subscription-1/
│   └── ...
└── export_results.json
```

## Troubleshooting

### aztfexport not found
```bash
export PATH=$PATH:$(go env GOPATH)/bin
```

### Authentication errors
```bash
az login
az account show
```

### Git push failures
- Check repository URLs in config
- Verify PAT token has permissions
- Ensure repositories exist in Azure DevOps

## Next Steps

1. Review exported Terraform code
2. Test with `terraform init && terraform plan`
3. Import existing state if needed
4. Set up CI/CD for Terraform deployments


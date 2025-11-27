# Azure Infrastructure Export to Terraform

Automated solution to export Azure infrastructure resources from multiple subscriptions using `aztfexport` and organize them into separate repositories for each subscription, with resource groups as subfolders.

## Features

- 🔍 **Multi-Subscription Support**: Export resources from 35+ Azure subscriptions
- 📦 **aztfexport Integration**: Uses Microsoft's official aztfexport tool for accurate Terraform generation
- 🗂️ **Organized Structure**: Subscription → Resource Group folder hierarchy
- 🚀 **Azure DevOps Pipeline**: Automated export and push to repositories
- 🔄 **Git Integration**: Automatic commit and push to Azure DevOps repos
- 📝 **Comprehensive Logging**: Detailed export results and summaries

## Prerequisites

- Python 3.10+
- Go 1.21+ (for aztfexport)
- Azure CLI or Service Principal credentials
- Azure DevOps organization and project
- Access to Azure subscriptions you want to export

## Installation

1. **Clone this repository:**
```bash
git clone <repository-url>
cd tf-migration-factory
```

2. **Install Python dependencies:**
```bash
pip install -r requirements.txt
```

3. **Install aztfexport:**
```bash
# Option 1: Using Go
go install github.com/Azure/aztfexport@latest

# Option 2: Download binary from releases
# https://github.com/Azure/aztfexport/releases
```

4. **Configure subscriptions:**
   - Edit `config/subscriptions.yaml` with your 35 subscription IDs
   - Configure repository URLs for each subscription

5. **Authenticate with Azure:**
   ```bash
   az login
   az account set --subscription "your-subscription-id"  # Optional: set default subscription
   ```
   
   The code uses your Azure CLI credentials automatically - no need for service principal!

## Configuration

### Subscription Configuration

Edit `config/subscriptions.yaml`:

```yaml
subscriptions:
  - id: "your-subscription-id-1"
    name: "Production Subscription 1"
    environment: "prod"
    repo_name: "terraform-prod-sub-1"
    repo_url: "https://dev.azure.com/org/project/_git/terraform-prod-sub-1"
    export_enabled: true
```

### Export Options

```yaml
aztfexport:
  # Resource types to export (empty = export all)
  # Example: ["Microsoft.Compute/virtualMachines", "Microsoft.Network/virtualNetworks"]
  resource_types: []
  
  # Resource groups to exclude from export (exact name match, case-sensitive)
  # Example:
  exclude_resource_groups:
    - "rg-shared-services"    # Exclude shared services
    - "rg-monitoring"         # Exclude monitoring resources
    - "rg-backup"             # Exclude backup resources
  
  # Resources to exclude (by full Azure resource ID)
  # Example:
  exclude_resources:
    - "/subscriptions/xxx/resourceGroups/rg-example/providers/Microsoft.Compute/virtualMachines/vm-to-exclude"
  
  # Additional aztfexport flags
  additional_flags: []
```

**Example: Excluding Resource Groups**

To exclude specific resource groups from export, add them to the `exclude_resource_groups` list:

```yaml
aztfexport:
  exclude_resource_groups:
    - "rg-shared-services"
    - "rg-monitoring"
    - "rg-temp-resources"
    - "rg-test-only"
```

**Note:** Resource group names must match exactly (case-sensitive). Wildcards are not supported.

## Usage

### Local Execution

#### Step 1: Export Resources (No Git Push)

First, export resources to verify the output before pushing to repositories:

```bash
# Make sure you're logged in to Azure
az login

# Run the export (git push is disabled by default)
python src/main.py
```

This will:
- Export all resources from configured subscriptions
- Save Terraform code to `./exports/` directory
- **NOT push to git repositories** (safe for verification)

#### Step 2: Review Exported Code

Review the exported Terraform code:

```bash
# Check the export directory structure
ls -la exports/

# Review a specific subscription's exports
ls -la exports/production-subscription-1/

# Review a specific resource group
ls -la exports/production-subscription-1/resource-group-1/
cat exports/production-subscription-1/resource-group-1/main.tf
```

#### Step 3: Enable Git Push (After Verification)

Once you're happy with the exports, enable git push:

**Prerequisites for Git Push:**
1. Set up Azure DevOps Personal Access Token (PAT):
   ```bash
   export AZURE_DEVOPS_PAT="your-pat-token"
   ```
   Or in Azure DevOps pipelines, use `SYSTEM_ACCESS_TOKEN` (automatically available).

2. Ensure you have "Contribute" permissions to the target repositories.

**Option 1: Edit config file (recommended)**
```yaml
# Edit config/subscriptions.yaml
git:
  push_to_repos: true  # Change from false to true
  branch: "main"      # Default branch (can be overridden per subscription)
```

Then run:
```bash
export AZURE_DEVOPS_PAT="your-pat-token"
python src/main.py
```

**Option 2: Use environment variable (overrides config)**
```bash
export PUSH_TO_REPOS=true
export GIT_BRANCH=main
export AZURE_DEVOPS_PAT="your-pat-token"
python src/main.py
```

**What happens during Git Push:**
- Creates `.gitignore` file (excludes Terraform state files, etc.)
- Creates `README.md` with subscription information
- Initializes git repository (if not already initialized)
- Commits all exported Terraform files
- Pushes to Azure DevOps repository
- Handles existing branches (pulls and merges if needed)

**Per-Subscription Branch Configuration:**
You can specify different branches per subscription:
```yaml
subscriptions:
  - id: "subscription-id-1"
    name: "Production Subscription 1"
    repo_url: "https://dev.azure.com/org/project/_git/repo-1"
    branch: "main"  # Override default branch for this subscription
  - id: "subscription-id-2"
    name: "Development Subscription 1"
    repo_url: "https://dev.azure.com/org/project/_git/repo-2"
    branch: "develop"  # Different branch for this subscription
```

### Output Structure

```
exports/
├── production-subscription-1/
│   ├── resource-group-1/
│   │   ├── main.tf
│   │   ├── providers.tf
│   │   └── terraform.tfstate (after import)
│   ├── resource-group-2/
│   │   └── ...
│   └── .git/  (only if git.push_to_repos: true)
├── development-subscription-1/
│   └── ...
└── export_results.json
```

**Note:** Git repositories (`.git/` folders) are only created when `git.push_to_repos: true` is set in config or `PUSH_TO_REPOS=true` environment variable is set.

## Azure DevOps Pipeline

### Setup

1. **Create Variable Group:**
   - Name: `TerraformExport`
   - Variables:
     - `azureServiceConnection`: Name of your Azure service connection
     - `AZURE_CLIENT_ID`: (Optional, if using service principal)
     - `AZURE_CLIENT_SECRET`: (Optional, if using service principal)
     - `AZURE_TENANT_ID`: (Optional, if using service principal)

2. **Configure Pipeline:**
   - Import `azure-pipelines.yml` to your Azure DevOps project
   - Grant pipeline permissions to access Azure subscriptions
   - Grant pipeline permissions to push to repositories

3. **Repository Permissions:**
   - Ensure the pipeline service account has Contribute permissions to all target repositories
   - Or use a PAT token with appropriate permissions

### Pipeline Variables

- `azureServiceConnection`: Azure service connection name
- `configPath`: Path to subscriptions config (default: `config/subscriptions.yaml`)
- `outputDir`: Output directory (default: `$(Pipeline.Workspace)/exports`)
- `gitBranch`: Branch to push to (default: `main`)

### Running the Pipeline

The pipeline will:
1. Install prerequisites (Go, Python, aztfexport)
2. Authenticate with Azure
3. Export resources for all enabled subscriptions
4. Initialize git repos in export directories
5. Commit and push to respective Azure DevOps repositories
6. Publish export results as artifacts

## Repository Structure

Each subscription gets its own repository with this structure:

```
terraform-{env}-sub-{id}/
├── resource-group-1/
│   ├── main.tf
│   ├── providers.tf
│   ├── terraform.tfstate (after import)
│   └── ...
├── resource-group-2/
│   └── ...
└── README.md (optional)
```

## Post-Export Steps

1. **Review Generated Code:**
   - Check exported Terraform files in each repository
   - Review resource configurations

2. **Import Existing State:**
   ```bash
   cd exports/subscription-name/resource-group-name
   terraform init
   terraform import <resource_type>.<name> <resource_id>
   ```

3. **Test and Validate:**
   ```bash
   terraform plan
   ```

4. **Commit Changes:**
   - Changes are automatically committed and pushed by the pipeline
   - Or commit manually if running locally

## Troubleshooting

### aztfexport Not Found

```bash
# Ensure Go is installed and in PATH
go version

# Install aztfexport
go install github.com/Azure/aztfexport@latest

# Add to PATH
export PATH=$PATH:$(go env GOPATH)/bin
```

### Authentication Issues

- Verify Azure CLI login: `az account show`
- Check service principal credentials
- Verify service connection in Azure DevOps

### Git Push Failures

1. **Authentication Errors:**
   ```bash
   # For local execution, set Azure DevOps PAT
   export AZURE_DEVOPS_PAT="your-pat-token"
   
   # In Azure DevOps pipelines, SYSTEM_ACCESS_TOKEN is automatically available
   ```

2. **Permission Errors:**
   - Ensure you have "Contribute" permissions to the target repository
   - Check that the PAT token has the correct scopes (Code: Read & Write)
   - Verify the repository URL in `config/subscriptions.yaml` is correct

3. **Repository Not Found:**
   - Verify the `repo_url` in `config/subscriptions.yaml` is correct
   - Ensure the repository exists in Azure DevOps
   - Check that the repository name matches the `repo_name` field

4. **Branch Issues:**
   - The tool automatically pulls and merges if the branch exists remotely
   - Ensure the branch name is correct (default: `main`)
   - You can override the branch per subscription in the config

5. **No Changes to Commit:**
   - If you see "No changes to commit", the export may not have created new files
   - Check the export logs to verify resources were exported
   - Review the export directory to ensure `.tf` files exist

### Export Timeouts

- Large resource groups may take time
- Consider exporting in batches
- Increase timeout in export_manager.py if needed

## Best Practices

1. **Start Small**: Test with 1-2 subscriptions first
2. **Review Before Push**: Disable `PUSH_TO_REPOS` initially to review exports
3. **Version Control**: All exports go to git repos for versioning
4. **Incremental Updates**: Re-run pipeline to update exports
5. **Resource Group Organization**: Keep related resources in same RG
6. **Tag Resources**: Use consistent tagging for better organization

## Security Considerations

- Store credentials in Azure DevOps variable groups (secure)
- Use service connections instead of hardcoded credentials
- Limit pipeline permissions to necessary subscriptions
- Review exported code before committing sensitive information
- Use Azure Key Vault for secrets if needed

## Support

For issues:
- Check aztfexport documentation: https://github.com/Azure/aztfexport
- Review Azure DevOps pipeline logs
- Check export_results.json for detailed error information

## License

[Add your license here]


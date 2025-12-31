# Azure DevOps Pipeline Setup Guide

This guide explains how to set up and use the Azure DevOps pipeline to export Azure resources to Terraform and push them to git repositories.

## Overview

The pipeline:
1. **Discovers** all subscriptions using default SPN (or groups by SPN if overrides configured)
2. **Exports** Azure resources using `aztfexport` for each subscription
3. **Executes in parallel** - multiple subscriptions export concurrently (grouped by SPN)
4. **Organizes** exports by subscription and resource group
5. **Pushes** exported code to separate git repositories (one per subscription)

### Execution Modes

- **All Subscriptions** (Default): Exports all discovered subscriptions in parallel
- **Selected Subscriptions** (Manual): Export specific subscriptions via pipeline parameters

## Prerequisites

1. **Azure DevOps Project** with:
   - Variable group: `TerraformExport`
   - Service connection for Azure authentication
   - Repositories created (or they will be created automatically)

2. **Azure Service Connection**:
   - Must have access to all subscriptions you want to export
   - Should have "Reader" role at minimum (for listing resources)
   - Recommended: "Contributor" role for full access

3. **Repository Permissions**:
   - Pipeline service account needs "Contribute" permissions to target repositories
   - Or use `SYSTEM_ACCESS_TOKEN` (automatically available in pipelines)

## Setup Steps

### Step 1: Create Variable Group

1. Go to **Pipelines** → **Library** → **Variable groups**
2. Create a new variable group named: `TerraformExport`
3. Add the following variables:

| Variable Name | Value | Description |
|--------------|-------|-------------|
| `azureServiceConnection` | `your-service-connection-name` | Name of your Azure service connection |
| `pushToRepos` | `true` | Set to `false` to disable git push (for testing) |

**Optional Variables:**
- `configPath`: Path to config file (default: `config/subscriptions.yaml`)
- `outputDir`: Output directory (default: `$(Pipeline.Workspace)/exports`)
- `gitBranch`: Default branch name (default: `main`)

### Step 2: Configure Service Connection

1. Go to **Project Settings** → **Service connections**
2. Create a new **Azure Resource Manager** service connection
3. Choose authentication method:
   - **Managed Identity** (recommended for managed pools)
   - **Service Principal** (for self-hosted agents)
4. Grant access to all subscriptions you want to export
5. Note the service connection name and add it to the variable group

### Step 3: Update Configuration File

Edit `config/subscriptions.yaml`:

```yaml
# Azure DevOps configuration
azure_devops:
  organization: "your-org"           # Your Azure DevOps organization
  project: "your-project"            # Your Azure DevOps project

# Git configuration
git:
  push_to_repos: true                # Enable git push
  branch: "main"                     # Default branch

# Pipeline execution configuration (optional)
pipeline:
  # Optional: SPN override per subscription
  # If subscription not listed, uses default SPN (from azureServiceConnection variable)
  subscription_spn_overrides:
    "subscription-id-1": "spn-prod-connection"  # Production uses prod SPN
    "subscription-id-2": "spn-dev-connection"  # Development uses dev SPN
    # Other subscriptions → use default SPN

# Note: Subscriptions are auto-discovered from Azure CLI
# No need to manually list them unless you want SPN overrides
```

### Step 4: Create Repositories (Optional)

Repositories can be created automatically, or you can create them manually:

1. Go to **Repos** → **Files**
2. Create a new repository for each subscription
3. Repository name should match `repo_name` in config
4. Initialize with a README (optional)

### Step 5: Import Pipeline

1. Go to **Pipelines** → **Pipelines**
2. Click **New pipeline**
3. Select your repository
4. Choose **Existing Azure Pipelines YAML file**
5. Select `azure-pipelines.yml` from the root
6. Review and save

## How It Works

### Export Process (All Subscriptions Mode)

1. **Discovery Stage**: 
   - Uses default SPN to discover all subscriptions
   - Checks SPN overrides per subscription (if configured)
   - Groups subscriptions by assigned SPN (default or override)
   - Creates matrix for parallel execution

2. **Export Stage**:
   - **Installation**: Installs Go, Python, and `aztfexport` (per job)
   - **Authentication**: Uses default service connection (compile-time resolution)
   - **Parallel Execution**: One job per SPN group, each processes its assigned subscriptions
   - For each subscription:
     - Lists all resource groups (excluding global excludes)
     - Exports each resource group using `aztfexport`
     - Creates folder structure: `exports/{subscription-name}/{resource-group-name}/`
   - **Git Push** (if enabled):
     - Initializes git repository in subscription folder
     - Creates `.gitignore` and `README.md`
     - Commits all Terraform files
     - Pushes to Azure DevOps repository

### Export Process (Selected Subscriptions Mode)

1. **Preparation Stage**:
   - Parses comma-separated subscription IDs from parameters
   - Validates subscriptions are accessible
   - Finds SPN for each subscription (override or default)
   - Creates matrix (one entry per subscription)

2. **Export Stage**:
   - Same as All Subscriptions Mode, but processes only selected subscriptions
   - Each subscription runs in parallel (matrix strategy)

### Repository Structure

Each subscription gets its own repository:

```
terraform-prod-sub-1/
├── .gitignore
├── README.md
├── resource-group-1/
│   ├── main.tf
│   ├── providers.tf
│   ├── terraform.tfstate
│   └── ...
├── resource-group-2/
│   └── ...
└── ...
```

### Git Operations

The pipeline:
- Uses `SYSTEM_ACCESS_TOKEN` for authentication (automatically available)
- Creates `.gitignore` to exclude Terraform state files
- Creates `README.md` with subscription information
- Commits with message: "Export Terraform code for subscription: {name}"
- Pushes to specified branch (default: `main`)

## Configuration Options

### Manual Run - Selected Subscriptions

When running the pipeline manually, you can select specific subscriptions:

1. Click "Run pipeline" in Azure DevOps
2. Set parameters:
   - **Subscription IDs**: `"sub-id-1,sub-id-2,sub-id-3"` (comma-separated)
   - **Run Mode**: `selected`
3. Pipeline will export only the specified subscriptions in parallel

**Example**: Export two subscriptions
- Subscription IDs: `"12345678-1234-1234-1234-123456789012,87654321-4321-4321-4321-210987654321"`
- Run Mode: `selected`

### SPN Override Configuration

Configure different service connections per subscription:

```yaml
pipeline:
  subscription_spn_overrides:
    "sub-id-1": "spn-prod-connection"   # Production subscription
    "sub-id-2": "spn-dev-connection"    # Development subscription
    # sub-id-3 not listed → uses default SPN
```

**Note**: Due to Azure DevOps compile-time validation, all jobs use the default SPN for authentication. The override is for reference/logging. True per-subscription SPN authentication would require inline jobs or manual authentication.

### Disable Git Push (Testing)

Set in variable group:
```
pushToRepos = false
```

Or in config file:
```yaml
git:
  push_to_repos: false
```

### Per-Subscription Branch

```yaml
git:
  branch: "main"  # Default branch
  # Per-subscription branch override not currently supported in parallel mode
```

### Custom Repository URLs

Repositories are auto-created based on subscription names. See `git_manager.py` for repository URL generation logic.

## Troubleshooting

### Authentication Issues

**Error**: "Azure CLI not authenticated"
- Verify service connection is configured correctly
- Check service connection has access to subscriptions
- Ensure service connection name matches variable group

### Git Push Failures

**Error**: "Failed to push to remote"
- Verify repository exists in Azure DevOps
- Check pipeline service account has "Contribute" permissions
- Ensure `SYSTEM_ACCESS_TOKEN` is available (automatic in pipelines)

**Error**: "Repository not found"
- Create repository manually, or
- Ensure `repo_name` or `repo_url` is correctly configured

### Export Failures

**Error**: "aztfexport not found"
- Pipeline should install it automatically
- Check Go installation step completed successfully

**Error**: "Timeout exporting resource group"
- Large resource groups may take > 1 hour
- Consider excluding resource groups or running in smaller batches

## Best Practices

1. **Start Small**: Test with 1-2 subscriptions first
2. **Disable Git Push Initially**: Set `pushToRepos: false` to verify exports
3. **Review Exports**: Check exported code before enabling git push
4. **Use Branching Strategy**: Use different branches for prod/dev/staging
5. **Monitor Pipeline**: Check pipeline logs for errors
6. **Backup**: Keep export artifacts for reference

## Pipeline Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `azureServiceConnection` | (required) | Azure service connection name |
| `configPath` | `config/subscriptions.yaml` | Path to config file |
| `outputDir` | `$(Pipeline.Workspace)/exports` | Output directory |
| `gitBranch` | `main` | Default git branch |
| `pushToRepos` | `true` | Enable/disable git push |

## Output Artifacts

The pipeline publishes:
- **terraform-exports**: Complete export directory with all Terraform files
- **export_results.json**: Summary of export operations

Download artifacts to review exports before they're pushed to git.


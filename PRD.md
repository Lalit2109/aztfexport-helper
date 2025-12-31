# Product Requirements Document (PRD)
## Azure Infrastructure Export to Terraform Factory

**Version:** 1.0  
**Date:** 2024-12-XX  
**Status:** Production

---

## 1. Executive Summary

### 1.1 Purpose
This document describes the Azure Infrastructure Export to Terraform Factory system - an automated solution that exports Azure infrastructure resources from multiple subscriptions using Microsoft's `aztfexport` tool and organizes them into separate Git repositories for version control and Infrastructure as Code (IaC) management.

### 1.2 Problem Statement
Organizations managing large Azure estates (35+ subscriptions) need to:
- Export existing Azure resources to Terraform format for IaC adoption
- Organize exports by subscription and resource group
- Maintain version control of exported Terraform code
- Monitor export operations and track backup status
- Automate the export process on a regular schedule

### 1.3 Solution Overview
The system provides:
- Automated multi-subscription resource export using `aztfexport`
- Organized folder structure (Subscription → Resource Group)
- Git integration for version control (one repository per subscription)
- Azure DevOps pipeline integration for scheduled automation
- Log Analytics integration for monitoring and reporting
- Email reporting via SendGrid for backup status

---

## 2. Product Overview

### 2.1 Core Functionality

#### 2.1.1 Resource Export
- **Tool**: Microsoft's `aztfexport` (official Azure resource export tool)
- **Scope**: Exports all resources from configured Azure subscriptions
- **Organization**: 
  - Top level: Subscription name
  - Second level: Resource group name (configurable)
- **Output Format**: Terraform HCL files (`.tf`)

#### 2.1.2 Subscription Discovery
- Automatically discovers all subscriptions accessible via Azure CLI
- Supports exclusion of specific subscriptions (by ID or name)
- Filters to only enabled subscriptions
- Supports prod/non-prod categorization for exclusions

#### 2.1.3 Resource Group Filtering
- **Exclusion Support**:
  - Global exclusions (applied to all subscriptions)
  - Per-subscription exclusions
  - Wildcard pattern matching (case-insensitive)
  - Exact name matching
- **Resource Type Filtering**:
  - Include only specific resource types
  - Exclude specific resource types (via Azure Resource Graph query)
- **Individual Resource Exclusion**:
  - Exclude specific resources by full Azure resource ID

#### 2.1.4 Git Integration
- **Repository Structure**: One repository per subscription
- **Branch Strategy**:
  - `main` branch: Always contains latest export
  - `backup-YYYY-MM-DD` branches: Historical backups (configurable retention)
- **Operations**:
  - Automatic repository initialization
  - `.gitignore` generation (excludes Terraform state files)
  - `README.md` generation with subscription metadata
  - Automatic commit and push
  - Backup branch creation and cleanup

#### 2.1.5 Monitoring & Reporting
- **Log Analytics Integration**:
  - Sends export status per subscription
  - Tracks: start/end time, duration, success/failure, resource group counts
  - Custom log table: `Infra_terraform_backup_CL`
- **Email Reporting**:
  - HTML email reports via SendGrid
  - Per-subscription metrics
  - Overall summary statistics
  - Configurable lookback period (default: 24 hours)

### 2.2 Key Features

1. **Multi-Subscription Support**: Handles 35+ subscriptions simultaneously
2. **Flexible Filtering**: Multiple exclusion mechanisms (RGs, resource types, individual resources)
3. **Automated Git Operations**: Full Git lifecycle management
4. **CI/CD Integration**: Azure DevOps pipeline with scheduled runs
5. **Comprehensive Logging**: Structured logging with multiple output levels
6. **Error Handling**: Graceful failure handling with detailed error messages
7. **Disk Space Monitoring**: Pre-flight checks for available disk space
8. **Cross-Platform**: Supports Windows, macOS, and Linux

---

## 3. System Architecture

### 3.1 Component Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Azure DevOps Pipeline                  │
│  ┌─────────────────────────────────────────────────────┐  │
│  │  Stage 1: Export                                    │  │
│  │  - Install prerequisites (Go, Python, aztfexport)   │  │
│  │  - Authenticate with Azure                          │  │
│  │  - Run main.py                                       │  │
│  └─────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────┐  │
│  │  Stage 2: Email Report                               │  │
│  │  - Query Log Analytics                               │  │
│  │  - Generate HTML report                              │  │
│  │  - Send via SendGrid                                 │  │
│  └─────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                    Python Application                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ main.py      │  │ export_      │  │ git_        │  │
│  │ (Orchestrator)│  │ manager.py   │  │ manager.py  │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│  ┌──────────────┐  ┌──────────────┐                      │
│  │ log_         │  │ logger.py    │                      │
│  │ analytics.py │  │              │                      │
│  └──────────────┘  └──────────────┘                      │
└─────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ Azure CLI    │   │ aztfexport   │   │ Git          │
│ (az)         │   │ (Go tool)    │   │              │
└──────────────┘   └──────────────┘   └──────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────┐
│                    Azure Cloud                           │
│  - Subscriptions                                         │
│  - Resource Groups                                       │
│  - Resources                                             │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│                    Azure DevOps                         │
│  - Git Repositories (one per subscription)               │
│  - Log Analytics Workspace                               │
└─────────────────────────────────────────────────────────┘
```

### 3.2 Core Modules

#### 3.2.1 `main.py` - Orchestrator
- **Responsibilities**:
  - Entry point for the application
  - Azure CLI authentication verification
  - Subscription discovery and filtering
  - Export orchestration per subscription
  - Git push coordination
  - Log Analytics integration
  - Summary reporting

#### 3.2.2 `export_manager.py` - Export Engine
- **Responsibilities**:
  - Configuration loading (YAML)
  - Subscription discovery via Azure CLI
  - Resource group discovery and filtering
  - `aztfexport` installation and execution
  - Resource group export orchestration
  - Disk space monitoring
  - Export directory cleanup

**Key Methods**:
- `get_subscriptions_from_azure()`: Discovers accessible subscriptions
- `_get_resource_groups()`: Lists RGs with exclusion logic
- `_export_resource_group()`: Executes aztfexport for a single RG
- `export_subscription()`: Exports all RGs in a subscription

#### 3.2.3 `git_manager.py` - Version Control
- **Responsibilities**:
  - Git repository initialization
  - Remote repository configuration
  - Branch management (main + backup branches)
  - Commit and push operations
  - Backup branch cleanup (retention management)
  - `.gitignore` and `README.md` generation

**Key Methods**:
- `push_to_repo()`: Main entry point for Git operations
- `_create_backup_branch()`: Creates dated backup branch
- `_cleanup_old_backup_branches()`: Removes old backups based on retention

#### 3.2.4 `log_analytics.py` - Monitoring
- **Responsibilities**:
  - HMAC-SHA256 authentication for Log Analytics API
  - Sending export status records
  - Data formatting and serialization

**Key Methods**:
- `send_subscription_backup_status()`: Sends per-subscription status
- `send_data()`: Generic data sending method

#### 3.2.5 `logger.py` - Logging
- **Responsibilities**:
  - Structured logging with multiple levels
  - Color-coded console output
  - Configurable log levels

### 3.3 External Dependencies

#### 3.3.1 Azure CLI (`az`)
- **Purpose**: Azure authentication and resource discovery
- **Usage**: 
  - `az account list`: Subscription discovery
  - `az group list`: Resource group discovery
  - `az account show`: Authentication verification

#### 3.3.2 aztfexport
- **Purpose**: Official Microsoft tool for Azure → Terraform export
- **Installation**: Via Go (`go install github.com/Azure/aztfexport@latest`)
- **Modes**:
  - Resource group mode: `aztfexport resource-group <rg-name>`
  - Query mode: `aztfexport query <kql-query>` (for resource type exclusions)

#### 3.3.3 Git
- **Purpose**: Version control operations
- **Operations**: init, add, commit, push, branch management

---

## 4. Configuration

### 4.1 Configuration File Structure

**Location**: `config/subscriptions.yaml`

```yaml
# Azure DevOps Configuration
azure_devops:
  organization: "your-org"
  project: "your-project"

# Git Configuration
git:
  push_to_repos: true              # Enable/disable git push
  branch: "main"                   # Default branch name
  backup_retention_count: 10       # Number of backup branches to keep

# Output Configuration
output:
  base_dir: "./exports"            # Export output directory
  create_rg_folders: true          # Create resource group subfolders
  cleanup_after_push: true        # Clean up export dir after git push

# Logging Configuration
logging:
  level: "INFO"                    # DEBUG, INFO, WARNING, ERROR

# Global Exclusions (applied to all subscriptions)
global_excludes:
  resource_groups:
    - "rg-shared-services"
    - "rg-monitoring-*"            # Wildcard support

# Subscription Exclusions
exclude_subscriptions:
  prod:
    - "subscription-id-1"
    - "Production Subscription 2"
  non-prod:
    - "subscription-id-2"

# aztfexport Configuration
aztfexport:
  # Resource groups to exclude (case-insensitive, supports wildcards)
  exclude_resource_groups:
    - "rg-temp-*"
    - "rg-test"
  
  # Resource types to exclude (uses Azure Resource Graph query)
  exclude_resource_types:
    - "Microsoft.Storage/storageAccounts"
  
  # Custom Azure Resource Graph query
  query: "resourceGroup == 'rg-name' and type == 'Microsoft.Compute/virtualMachines'"
  
  # Resources to exclude by full ID
  exclude_resources:
    - "/subscriptions/xxx/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
  
  # Only export these resource types (if specified, only these are exported)
  resource_types:
    - "Microsoft.Compute/virtualMachines"
    - "Microsoft.Network/virtualNetworks"
  
  # Additional aztfexport command-line flags
  additional_flags:
    - "--parallelism"
    - "10"
```

### 4.2 Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `CONFIG_PATH` | Path to config YAML file | No | `config/subscriptions.yaml` |
| `OUTPUT_DIR` | Export output directory | No | `./exports` |
| `PUSH_TO_REPOS` | Enable git push (`true`/`false`) | No | `false` |
| `GIT_BRANCH` | Default git branch | No | `main` |
| `LOG_LEVEL` | Logging level | No | `INFO` |
| `AZURE_DEVOPS_PAT` | Azure DevOps PAT token | Yes* | - |
| `SYSTEM_ACCESS_TOKEN` | Azure DevOps system token | Yes* | - |
| `LOG_ANALYTICS_WORKSPACE_ID` | Log Analytics workspace ID | No | - |
| `LOG_ANALYTICS_SHARED_KEY` | Log Analytics shared key | No | - |

*Required only if `push_to_repos: true`

### 4.3 Azure DevOps Pipeline Variables

**Variable Group**: `TerraformExport`

| Variable | Description | Required |
|----------|-------------|----------|
| `azureServiceConnection` | Azure service connection name | Yes |
| `LOG_ANALYTICS_WORKSPACE_ID` | Log Analytics workspace ID | No |
| `LOG_ANALYTICS_SHARED_KEY` | Log Analytics shared key | No |
| `SendGridApiKey` | SendGrid API key for email | No |
| `SendGridFrom` | Email sender address | No |
| `SendGridTo` | Email recipient(s), comma-separated | No |
| `Environment` | Environment name (e.g., "Prod") | No |

---

## 5. Data Flow

### 5.1 Export Flow

```
1. Application Start (main.py)
   │
   ├─> Load Configuration (YAML)
   │
   ├─> Verify Azure CLI Authentication
   │
   ├─> Discover Subscriptions (Azure CLI)
   │   └─> Filter excluded subscriptions
   │
   ├─> For Each Subscription:
   │   │
   │   ├─> Discover Resource Groups (Azure CLI)
   │   │   └─> Apply exclusion filters (global + local)
   │   │
   │   ├─> For Each Resource Group:
   │   │   │
   │   │   ├─> Build aztfexport Command
   │   │   │   ├─> Check for query mode (resource type exclusions)
   │   │   │   ├─> Apply resource type filters
   │   │   │   └─> Apply individual resource exclusions
   │   │   │
   │   │   ├─> Execute aztfexport
   │   │   │   └─> Output: Terraform files (.tf)
   │   │   │
   │   │   └─> Record Success/Failure
   │   │
   │   ├─> If Git Push Enabled:
   │   │   │
   │   │   ├─> Initialize Git Repository
   │   │   ├─> Create .gitignore and README.md
   │   │   ├─> Commit All Changes
   │   │   ├─> Push to Main Branch
   │   │   ├─> Create Backup Branch (backup-YYYY-MM-DD)
   │   │   ├─> Cleanup Old Backup Branches
   │   │   └─> Cleanup Export Directory (if configured)
   │   │
   │   └─> Send Status to Log Analytics
   │
   └─> Generate Summary Report
```

### 5.2 Git Repository Structure

```
terraform-{subscription-name}/
├── .git/
├── .gitignore
├── README.md
├── resource-group-1/
│   ├── main.tf
│   ├── providers.tf
│   ├── terraform.tfstate (if imported)
│   └── ...
├── resource-group-2/
│   └── ...
└── ...
```

### 5.3 Log Analytics Data Model

**Table**: `Infra_terraform_backup_CL`

| Field | Type | Description |
|-------|------|-------------|
| `TimeGenerated` | datetime | Export start time |
| `SubscriptionId` | string | Azure subscription ID |
| `SubscriptionName` | string | Subscription display name |
| `Status` | string | `success` or `failed` |
| `StartTime` | datetime | Export start time |
| `EndTime` | datetime | Export end time |
| `DurationSeconds` | double | Export duration in seconds |
| `TotalResourceGroups` | int | Total RGs in subscription |
| `SuccessfulResourceGroups` | int | Successfully exported RGs |
| `FailedResourceGroups` | int | Failed RG exports |
| `GitPushStatus` | string | `success`, `failed`, or `skipped` |
| `ErrorMessage` | string | Error message (if failed) |

---

## 6. Use Cases

### 6.1 Initial Export (Discovery Mode)
**Scenario**: First-time export of all subscriptions

1. Set `push_to_repos: false` in config
2. Run export locally: `python src/main.py`
3. Review exported Terraform code in `./exports/`
4. Verify resource group organization
5. Check for excluded resources
6. Enable git push and re-run

### 6.2 Scheduled Weekly Backup
**Scenario**: Automated weekly export via Azure DevOps pipeline

1. Pipeline runs every Friday at 8:00 AM UTC (cron schedule)
2. Exports all enabled subscriptions
3. Pushes to Git repositories (main + backup branch)
4. Sends email report with status summary
5. Logs all operations to Log Analytics

### 6.3 Selective Export
**Scenario**: Export only specific resource types

```yaml
aztfexport:
  resource_types:
    - "Microsoft.Compute/virtualMachines"
    - "Microsoft.Network/virtualNetworks"
```

### 6.4 Exclusion-Based Export
**Scenario**: Export everything except specific resource groups

```yaml
aztfexport:
  exclude_resource_groups:
    - "rg-shared-services"
    - "rg-monitoring-*"
global_excludes:
  resource_groups:
    - "rg-temp-*"
```

---

## 7. Error Handling

### 7.1 Error Categories

1. **Authentication Errors**
   - Azure CLI not authenticated → Exit with clear message
   - PAT token missing → Skip git push, continue export

2. **Export Errors**
   - aztfexport not found → Attempt auto-install, fail if not possible
   - Resource group export timeout → Log error, continue with next RG
   - Export failure → Record in results, continue processing

3. **Git Errors**
   - Repository not found → Log error with creation instructions
   - Push failure → Log error, export still succeeds
   - Branch conflicts → Auto-merge or force push (configurable)

4. **Configuration Errors**
   - Invalid YAML → Exit with parse error
   - Missing required fields → Use defaults or exit with error

### 7.2 Error Recovery

- **Per-Subscription**: Failures in one subscription don't stop others
- **Per-Resource Group**: Failed RG exports are logged but don't stop subscription export
- **Git Operations**: Git failures don't prevent export completion
- **Log Analytics**: Log Analytics failures are logged but don't stop export

---

## 8. Performance Considerations

### 8.1 Scalability
- **Subscriptions**: Tested with 35+ subscriptions
- **Resource Groups**: No hard limit, but large RGs may timeout (1 hour default)
- **Parallel Processing**: Currently sequential (one RG at a time, one subscription at a time)

### 8.2 Optimization Opportunities
- Parallel resource group exports within a subscription
- Parallel subscription processing
- Incremental exports (only changed resources)
- Caching of subscription/RG lists

### 8.3 Resource Usage
- **Disk Space**: Monitored before export (5% minimum free space)
- **Memory**: Moderate (Python process + subprocess calls)
- **Network**: Azure API calls for discovery, Git operations for push

---

## 9. Security Considerations

### 9.1 Authentication
- **Azure**: Uses Azure CLI credentials or service principal
- **Git**: Uses Azure DevOps PAT token or SYSTEM_ACCESS_TOKEN
- **Log Analytics**: Uses shared key with HMAC-SHA256

### 9.2 Credential Management
- Credentials stored in Azure DevOps variable groups (encrypted)
- PAT tokens never logged or exposed
- Service principal credentials in secure variable group

### 9.3 Access Control
- Pipeline service account needs:
  - Reader access to Azure subscriptions
  - Contribute access to Git repositories
  - Write access to Log Analytics workspace

### 9.4 Data Protection
- `.gitignore` excludes sensitive files (`.tfstate`, `.tfvars`)
- Exported code may contain resource IDs (review before committing)

---

## 10. Monitoring & Observability

### 10.1 Logging
- **Console Output**: Color-coded, structured logging
- **Log Levels**: DEBUG, INFO, WARNING, ERROR
- **Structured Format**: Includes timestamps, context, status

### 10.2 Metrics
- Export duration per subscription
- Success/failure rates (subscriptions and resource groups)
- Git push success rate
- Resource group counts

### 10.3 Alerts (Future)
- Failed export runs
- Low success rates
- Export timeouts
- Git push failures

### 10.4 Reporting
- **Email Reports**: HTML format via SendGrid
  - Overall summary (total subscriptions, runs, success rates)
  - Per-subscription details
  - Configurable lookback period
- **Log Analytics Queries**: Custom KQL queries for analysis

---

## 11. Future Enhancement Opportunities

### 11.1 Planned Features (from TODO.md)
- **Git Branch Management Strategy**: 
  - Always push to `main` (latest)
  - Create dated backup branches
  - Automatic cleanup of old backups
  - Status: Partially implemented (backup branches exist, but main strategy needs refinement)

### 11.2 Potential Enhancements

#### 11.2.1 Performance
- Parallel resource group exports
- Parallel subscription processing
- Incremental export support (delta exports)
- Export result caching

#### 11.2.2 Functionality
- Export scheduling per subscription
- Export notifications (Slack, Teams, etc.)
- Export validation (terraform validate)
- Export comparison (diff between runs)
- Resource dependency analysis
- Export rollback capability

#### 11.2.3 Integration
- Terraform Cloud/Enterprise integration
- Azure Policy compliance checking
- Cost analysis integration
- Security scanning (Checkov, tfsec)

#### 11.2.4 User Experience
- Web dashboard for export status
- Export history visualization
- Export scheduling UI
- Configuration management UI

#### 11.2.5 Reliability
- Retry logic for failed exports
- Export resume capability
- Export checkpointing
- Health checks and self-healing

---

## 12. Technical Specifications

### 12.1 Technology Stack

| Component | Technology | Version |
|-----------|------------|---------|
| Language | Python | 3.10+ |
| Configuration | YAML | - |
| Azure Tool | aztfexport | Latest (Go-based) |
| Version Control | Git | - |
| CI/CD | Azure DevOps | - |
| Monitoring | Azure Log Analytics | - |
| Email | SendGrid API | v3 |
| Authentication | Azure CLI / Service Principal | - |

### 12.2 Dependencies

**Python Packages** (requirements.txt):
- `pyyaml>=6.0` - YAML configuration parsing
- `python-dotenv>=1.0.0` - Environment variable management
- `gitpython>=3.1.0` - Git operations (not currently used, uses subprocess)
- `requests>=2.31.0` - HTTP requests for Log Analytics API

### 12.3 System Requirements

- **Operating System**: Windows, macOS, Linux
- **Python**: 3.10 or higher
- **Go**: 1.21+ (for aztfexport installation)
- **Azure CLI**: Latest version
- **Git**: Latest version
- **Disk Space**: Sufficient for exports (monitored, 5% minimum)

### 12.4 API Integrations

1. **Azure Management API** (via Azure CLI)
   - Subscription listing
   - Resource group listing

2. **Azure DevOps REST API** (via Git)
   - Repository operations
   - Branch management

3. **Azure Log Analytics Data Collector API**
   - Custom log ingestion
   - HMAC-SHA256 authentication

4. **SendGrid API v3**
   - Email sending
   - HTML email support

---

## 13. Testing Strategy

### 13.1 Current Testing
- Manual testing with real Azure subscriptions
- Pipeline testing in Azure DevOps
- Export validation (file existence, structure)

### 13.2 Recommended Testing Enhancements
- Unit tests for configuration parsing
- Unit tests for exclusion logic
- Integration tests with mock Azure CLI
- Integration tests with mock Git operations
- End-to-end tests with test subscriptions
- Performance tests with large resource counts

---

## 14. Deployment

### 14.1 Local Deployment
1. Clone repository
2. Install Python dependencies: `pip install -r requirements.txt`
3. Install Go and aztfexport
4. Configure `config/subscriptions.yaml`
5. Authenticate with Azure: `az login`
6. Run: `python src/main.py`

### 14.2 Azure DevOps Pipeline Deployment
1. Create variable group `TerraformExport`
2. Configure Azure service connection
3. Import `azure-pipelines.yml`
4. Configure schedule (default: Friday 8 AM UTC)
5. Grant repository permissions to pipeline service account

### 14.3 Prerequisites
- Azure DevOps organization and project
- Azure service connection with subscription access
- Git repositories (created automatically or pre-created)
- Log Analytics workspace (optional)
- SendGrid account (optional, for email reports)

---

## 15. Maintenance & Support

### 15.1 Regular Maintenance
- Update `aztfexport` to latest version
- Review and update exclusion lists
- Monitor export success rates
- Review Log Analytics data
- Clean up old export artifacts

### 15.2 Troubleshooting
- Check Azure CLI authentication
- Verify subscription access
- Review export logs for errors
- Check Git repository permissions
- Verify Log Analytics workspace access
- Review disk space availability

### 15.3 Known Limitations
- Sequential processing (not parallel)
- Export timeouts for very large resource groups (1 hour limit)
- No incremental export support
- No export validation (terraform validate)
- Wildcard exclusions are case-insensitive but exact match preferred

---

## 16. Glossary

- **aztfexport**: Microsoft's official tool for exporting Azure resources to Terraform
- **IaC**: Infrastructure as Code
- **PAT**: Personal Access Token (Azure DevOps)
- **RG**: Resource Group
- **KQL**: Kusto Query Language (used by Azure Log Analytics)
- **HCL**: HashiCorp Configuration Language (Terraform syntax)

---

## 17. Appendices

### 17.1 Example Configuration Files

See `config/examples.yaml` for detailed configuration examples.

### 17.2 Pipeline Setup Guide

See `PIPELINE_SETUP.md` for detailed Azure DevOps pipeline setup instructions.

### 17.3 Code Structure

```
tf-migration-factory/
├── src/
│   ├── main.py              # Entry point, orchestration
│   ├── export_manager.py    # Export logic, aztfexport integration
│   ├── git_manager.py       # Git operations, branch management
│   ├── log_analytics.py     # Log Analytics integration
│   └── logger.py            # Logging utilities
├── config/
│   ├── subscriptions.yaml   # Main configuration file
│   └── examples.yaml        # Configuration examples
├── azure-pipelines/
│   ├── azure-pipelines.yml  # Main pipeline definition
│   └── backup-monitor/
│       └── send-backup-report.ps1  # Email report script
├── requirements.txt         # Python dependencies
└── README.md                # User documentation
```

---

## 18. Change Log

### Version 1.0 (Current)
- Initial production release
- Multi-subscription export support
- Git integration with backup branches
- Log Analytics integration
- Email reporting via SendGrid
- Azure DevOps pipeline integration
- Flexible exclusion mechanisms

---

**Document End**


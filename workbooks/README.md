# Azure Monitor Workbook for Terraform Backup Monitoring

This workbook provides comprehensive monitoring and visualization for Terraform backup exports tracked in Log Analytics.

## Installation

1. Navigate to your Log Analytics workspace in Azure Portal
2. Go to **Workbooks** section
3. Click **New** to create a new workbook
4. Click **</>** (Advanced Editor) icon
5. Replace the default JSON with the contents of `terraform-backup-monitor.json`
6. Click **Apply** and then **Done Editing**
7. Save the workbook with a name like "Terraform Backup Monitor"

## Workbook Sections

### 1. Summary Statistics
- Total exports count
- Successful vs failed exports
- Success rate percentage
- Average duration
- Total resource groups processed
- Successful/failed resource group counts

### 2. Subscription Status
- Per-subscription breakdown
- Export counts and success rates
- Average duration per subscription
- Resource group statistics

### 3. Export Status Over Time
- Time series chart showing success/failure trends
- Helps identify patterns or issues over time

### 4. Duration Statistics
- Average, minimum, and maximum export durations
- Helps track performance trends

### 5. Git Push Status Distribution
- Pie chart showing git push success/failure/skipped rates
- Helps monitor git integration health

### 6. Recent Failures
- Last 50 failed exports with error messages
- Includes subscription details and failure reasons

### 7. Resource Group Export Summary
- Overall resource group export statistics
- Success rate across all resource groups

### 8. Recent Export Activity
- Last 100 export operations
- Detailed view of each export with status and metrics

## Parameters

- **TimeRange**: Filter data by time range (1 hour, 24 hours, 7 days, 30 days, or custom)
- **Subscription**: Filter by specific subscription name (optional)

## Prerequisites

- Log Analytics workspace with `Infra_terraform_backup` table
- Data being sent from the Terraform export pipeline
- Appropriate permissions to view Log Analytics data

## Customization

You can modify the workbook JSON to:
- Add additional visualizations
- Change time ranges
- Add filters for specific environments
- Customize color schemes
- Add alerting thresholds


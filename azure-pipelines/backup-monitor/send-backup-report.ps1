<#
    Script: send-backup-report.ps1

    Purpose:
      - Query Log Analytics for recent Terraform backup runs
      - Generate HTML summary (per subscription + overall)
      - Send report email via SendGrid after each backup run

    Notes:
      - Intended to run in Azure Pipelines (AzurePowerShell task)
      - Uses Az.Accounts + Az.OperationalInsights
      - Reads from custom log table written by this repo: Infra_terraform_backup_CL
#>

param(
    [Parameter(Mandatory = $true)]
    [string] $LogAnalyticsWorkspaceId,

    [Parameter(Mandatory = $true)]
    [string] $LogAnalyticsSharedKey,  # not used for query, kept for consistency

    [Parameter(Mandatory = $true)]
    [string] $SendGridApiKey,

    [Parameter(Mandatory = $true)]
    [string] $SendGridFrom,

    [Parameter(Mandatory = $true)]
    [string] $SendGridTo,

    [Parameter(Mandatory = $false)]
    [string] $EnvName = "Prod",

    [Parameter(Mandatory = $false)]
    [int] $LookbackHours = 24
)

Write-Host "Starting Terraform backup report. Environment=$EnvName LookbackHours=$LookbackHours"

# Ensure required modules
if (-not (Get-Module -ListAvailable -Name Az.Accounts)) {
    throw "Az.Accounts module is required on the agent."
}
if (-not (Get-Module -ListAvailable -Name Az.OperationalInsights)) {
    throw "Az.OperationalInsights module is required on the agent."
}

Import-Module Az.Accounts -ErrorAction Stop
Import-Module Az.OperationalInsights -ErrorAction Stop

$nowUtc = [DateTime]::UtcNow
$fromTime = $nowUtc.AddHours(-1 * $LookbackHours)

Write-Host "Querying Log Analytics for backup data from last $LookbackHours hours (since $($fromTime.ToString('u')))..."

# KQL for Infra_terraform_backup_CL
$kqlQuery = @"
Infra_terraform_backup_CL
| where TimeGenerated > ago(${LookbackHours}h)
| summarize
    LastRunTime = max(TimeGenerated),
    Runs = count(),
    TotalResourceGroups = sum(TotalResourceGroups_d),
    SuccessfulResourceGroups = sum(SuccessfulResourceGroups_d),
    FailedResourceGroups = sum(FailedResourceGroups_d),
    SuccessfulRuns = countif(Status_s == "success"),
    FailedRuns = countif(Status_s == "failed"),
    LastStatus = arg_max(TimeGenerated, Status_s),
    LastGitPushStatus = arg_max(TimeGenerated, GitPushStatus_s)
    by SubscriptionId_s, SubscriptionName_s
| extend
    RunSuccessRate = iff(Runs == 0, 0.0, round(SuccessfulRuns * 100.0 / Runs, 1)),
    RGSuccessRate = iff(TotalResourceGroups == 0, 0.0, round(SuccessfulResourceGroups * 100.0 / TotalResourceGroups, 1))
| order by SubscriptionName_s asc
"@

try {
    Write-Host "Verifying Azure context..."
    $context = Get-AzContext
    if (-not $context) {
        throw "No Azure context found. Ensure AzurePowerShell task is logged in."
    }
    Write-Host "Azure context: Account=$($context.Account.Id) Subscription=$($context.Subscription.Id)"

    $timespan = New-TimeSpan -Hours $LookbackHours
    $queryResult = Invoke-AzOperationalInsightsQuery `
        -WorkspaceId $LogAnalyticsWorkspaceId `
        -Timespan $timespan `
        -Query $kqlQuery `
        -ErrorAction Stop

    $reportData = @()
    if ($queryResult -and $queryResult.PSObject.Properties['Results'] -and $null -ne $queryResult.Results) {
        $reportData = $queryResult.Results
    }

    $reportDataCount = @($reportData).Count
    Write-Host "Found $reportDataCount subscription(s) with backup data in the last $LookbackHours hours."
}
catch {
    Write-Error "Failed to query Log Analytics: $_"
    throw
}

if ($reportDataCount -eq 0) {
    # No data → simple notification
    $htmlBody = @"
<h2>Terraform Backup Report (Last $LookbackHours Hours)</h2>
<p><strong>Environment:</strong> $EnvName</p>
<p><strong>Report Period:</strong> $($fromTime.ToString('u')) to $($nowUtc.ToString('u')) (UTC)</p>
<p><strong>Status:</strong> No backup records found in Log Analytics for this period.</p>
"@
}
else {
    # Overall summary
    $totalSubs = $reportDataCount
    $totalRuns = ($reportData | Measure-Object -Property Runs -Sum).Sum
    $totalRGs = ($reportData | Measure-Object -Property TotalResourceGroups -Sum).Sum
    $totalSuccessfulRGs = ($reportData | Measure-Object -Property SuccessfulResourceGroups -Sum).Sum
    $totalFailedRGs = ($reportData | Measure-Object -Property FailedResourceGroups -Sum).Sum
    $totalSuccessfulRuns = ($reportData | Measure-Object -Property SuccessfulRuns -Sum).Sum
    $totalFailedRuns = ($reportData | Measure-Object -Property FailedRuns -Sum).Sum

    $runSuccessRate = if ($totalRuns -gt 0) {
        [math]::Round(($totalSuccessfulRuns * 100.0 / $totalRuns), 1)
    } else { 0.0 }

    $rgSuccessRate = if ($totalRGs -gt 0) {
        [math]::Round(($totalSuccessfulRGs * 100.0 / $totalRGs), 1)
    } else { 0.0 }

    $summaryHtml = @"
<h2>Terraform Backup Report (Last $LookbackHours Hours)</h2>
<p><strong>Environment:</strong> $EnvName</p>
<p><strong>Report Period:</strong> $($fromTime.ToString('u')) to $($nowUtc.ToString('u')) (UTC)</p>
<p><strong>Report Generated:</strong> $($nowUtc.ToString('u')) (UTC)</p>

<h3>Overall Summary</h3>
<table border="1" cellspacing="0" cellpadding="5" style="margin-bottom: 20px;">
  <tr><th>Metric</th><th>Value</th></tr>
  <tr><td>Total Subscriptions</td><td><strong>$totalSubs</strong></td></tr>
  <tr><td>Total Runs</td><td><strong>$totalRuns</strong></td></tr>
  <tr><td>Successful Runs</td><td><strong>$totalSuccessfulRuns</strong></td></tr>
  <tr><td>Failed Runs</td><td><strong style="color:#ff0000;">$totalFailedRuns</strong></td></tr>
  <tr><td>Run Success Rate</td><td><strong>$runSuccessRate %</strong></td></tr>
  <tr><td>Total Resource Groups</td><td><strong>$totalRGs</strong></td></tr>
  <tr><td>Successful RG Exports</td><td><strong>$totalSuccessfulRGs</strong></td></tr>
  <tr><td>Failed RG Exports</td><td><strong style="color:#ff0000;">$totalFailedRGs</strong></td></tr>
  <tr><td>RG Success Rate</td><td><strong>$rgSuccessRate %</strong></td></tr>
</table>

<h3>Per-Subscription Detail</h3>
<p>The table below shows backup metrics per subscription for the selected period.</p>
"@

    $rows = ""
    foreach ($item in $reportData) {
        $subId   = $item.SubscriptionId_s
        $subName = $item.SubscriptionName_s
        $runs    = [int]$item.Runs
        $succRuns = [int]$item.SuccessfulRuns
        $failRuns = [int]$item.FailedRuns
        $totalRG = [int]$item.TotalResourceGroups
        $succRG  = [int]$item.SuccessfulResourceGroups
        $failRG  = [int]$item.FailedResourceGroups
        $runRate = [double]$item.RunSuccessRate
        $rgRate  = [double]$item.RGSuccessRate
        $lastStatus = $item.LastStatus
        $gitStatus  = $item.LastGitPushStatus

        $rowStyle = ""
        if ($failRuns -gt 0 -or $failRG -gt 0) {
            $rowStyle = " style='background-color:#ffcccc;'"  # highlight failures
        }

        $rows += "<tr$rowStyle>" +
                 "<td><code>$subId</code></td>" +
                 "<td><strong>$subName</strong></td>" +
                 "<td>$runs</td>" +
                 "<td>$succRuns</td>" +
                 "<td>$failRuns</td>" +
                 "<td>$runRate %</td>" +
                 "<td>$totalRG</td>" +
                 "<td>$succRG</td>" +
                 "<td>$failRG</td>" +
                 "<td>$rgRate %</td>" +
                 "<td>$lastStatus</td>" +
                 "<td>$gitStatus</td>" +
                 "</tr>"
    }

    $detailTable = @"
<table border="1" cellspacing="0" cellpadding="5" style="width: 100%;">
  <tr style="background-color:#e0e0e0;">
    <th>Subscription ID</th>
    <th>Subscription Name</th>
    <th>Runs</th>
    <th>Successful Runs</th>
    <th>Failed Runs</th>
    <th>Run Success %</th>
    <th>Total RGs</th>
    <th>Successful RGs</th>
    <th>Failed RGs</th>
    <th>RG Success %</th>
    <th>Last Status</th>
    <th>Last Git Push</th>
  </tr>
  $rows
</table>
"@

    $htmlBody = $summaryHtml + $detailTable
}

# Build SendGrid payload
$subjectPrefix = "[$EnvName] Terraform Backup"
$subject = "$subjectPrefix - Report (Last $LookbackHours Hours)"

$toList = $SendGridTo.Split(",", [System.StringSplitOptions]::RemoveEmptyEntries).ForEach({ $_.Trim() }) | Where-Object { $_ }
if (-not $toList -or $toList.Count -eq 0) {
    throw "SendGridTo is empty after parsing. Provide at least one recipient email address."
}

$personalizations = @(
    @{
        to      = @($toList | ForEach-Object { @{ email = $_ } })
        subject = $subject
    }
)

$sgBody = @{
    personalizations = $personalizations
    from             = @{ email = $SendGridFrom }
    content          = @(
        @{
            type  = "text/html"
            value = $htmlBody
        }
    )
}

$sgJson = $sgBody | ConvertTo-Json -Depth 10

Write-Host "Sending Terraform backup report via SendGrid to $SendGridTo"

$headers = @{
    "Authorization" = "Bearer $SendGridApiKey"
    "Content-Type"  = "application/json"
}

try {
    $response = Invoke-RestMethod -Method Post -Uri "https://api.sendgrid.com/v3/mail/send" -Headers $headers -Body $sgJson -ErrorAction Stop
    Write-Host "SendGrid email request completed successfully."
    Write-Host "Backup report sent to $($toList.Count) recipient(s)."
}
catch {
    Write-Error "Failed to send email via SendGrid. $_"
    throw
}

Write-Host "Terraform backup report generation completed."



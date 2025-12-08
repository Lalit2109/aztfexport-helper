# TODO - Future Enhancements

## Git Branch Management Strategy

**Status:** Parked for later implementation  
**Date:** 2024-12-05  
**Priority:** Medium

### Feature Description
Implement a better git branch management strategy for weekly Terraform exports:

1. **Main Branch Strategy:**
   - Always push latest export to `main` branch
   - Use merge instead of force push for main branch
   - Main branch always contains the most recent export

2. **Backup Branch Strategy:**
   - Create dated backup branches for each export: `backup-YYYY-MM-DD`
   - Keep only the last N days of backup branches (configurable, default: 7 days)
   - Automatically cleanup old backup branches

3. **Configuration:**
   - Add `backup_retention_days` config option (default: 7)
   - Make retention period configurable per subscription if needed

4. **Schedule:**
   - Configure pipeline to run weekly on Friday morning
   - Add cron schedule: `0 8 * * 5` (Every Friday at 8:00 AM UTC)

### Implementation Details

#### Changes Required:

1. **`src/git_manager.py`:**
   - Modify `_get_branch()` to return "main" for main branch
   - Add `_get_backup_branch_name()` method
   - Add `_create_backup_branch()` method
   - Add `_cleanup_old_backup_branches()` method
   - Modify `_push_to_remote()` to support main branch with merge
   - Update `push_to_repo()` to:
     - Push to main first
     - Create backup branch
     - Cleanup old backup branches

2. **`config/subscriptions.yaml`:**
   - Add `backup_retention_days: 7` to git configuration

3. **`azure-pipelines.yml`:**
   - Add schedule trigger for Friday morning runs

### Benefits
- Latest export always accessible on main branch
- Historical backups available via dated branches
- Automatic cleanup prevents branch proliferation
- Configurable retention period
- Safe main branch updates (no force push)

### Usage Examples
```bash
# Checkout latest export
git checkout main

# Checkout backup from 7 days ago
git checkout backup-2024-12-05

# List all backup branches
git branch -r | grep backup-

# Compare current with backup
git diff backup-2024-12-05 main
```

### Notes
- Current implementation creates timestamped branches for each run
- This causes branch proliferation and makes it hard to manage
- New strategy will keep main clean and use backup branches for history


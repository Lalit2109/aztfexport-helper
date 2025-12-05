"""
Main script to orchestrate Azure resource export to Terraform
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

from export_manager import ExportManager
from log_analytics import LogAnalyticsSender
from logger import get_logger


def main():
    """Main execution function"""
    load_dotenv()
    logger = get_logger()
    
    config_path = os.getenv('CONFIG_PATH', 'config/subscriptions.yaml')
    
    logger.info("=" * 70)
    logger.info("Azure Infrastructure Export to Terraform")
    logger.info("Using aztfexport for resource export")
    logger.info("=" * 70)
    logger.info("")
    
    export_manager = ExportManager(config_path)
    logger = get_logger()
    
    logger.info("Checking Azure CLI authentication...")
    az_cli_path = export_manager.az_cli_path
    
    if az_cli_path != 'az' and not os.path.exists(az_cli_path):
        logger.error(f"Azure CLI not found at expected path: {az_cli_path}")
        logger.info("Please ensure Azure CLI is installed and in your PATH")
        sys.exit(1)
    
    try:
        result = subprocess.run(
            [az_cli_path, 'account', 'show'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            account_info = subprocess.run(
                [az_cli_path, 'account', 'show', '--query', '{name:name, id:id}', '-o', 'json'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if account_info.returncode == 0:
                account = json.loads(account_info.stdout)
                logger.success("Azure CLI is authenticated")
                logger.info(f"Account: {account.get('name', 'N/A')}")
                logger.info(f"Subscription ID: {account.get('id', 'N/A')}")
            else:
                logger.warning("Could not get account information")
        else:
            logger.error("Not logged in to Azure CLI")
            logger.info("Please run: az login")
            sys.exit(1)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        logger.error("Azure CLI not found")
        logger.info("Please install Azure CLI: https://docs.microsoft.com/cli/azure/install-azure-cli")
        sys.exit(1)
    except Exception as e:
        logger.warning(f"Error checking Azure CLI: {str(e)}")
        logger.info("Continuing anyway...")
    
    logger.info("")
    logger.info("Exporting Azure resources...")
    logger.info("-" * 70)
    
    # Initialize Log Analytics sender
    log_analytics = LogAnalyticsSender()
    
    # Check if git push is enabled
    push_to_repos = os.getenv('PUSH_TO_REPOS', 'false').lower() == 'true'
    push_to_repos = push_to_repos or export_manager.config.get('git', {}).get('push_to_repos', False)
    
    # Get subscription list and exclude list
    subscriptions = export_manager.config.get('subscriptions', [])
    exclude_subscriptions = export_manager.config.get('exclude_subscriptions', [])
    create_rg_folders = export_manager.config.get('output', {}).get('create_rg_folders', True)
    
    # Install aztfexport once
    try:
        export_manager._install_aztfexport()
    except Exception as e:
        logger.error(f"Error with aztfexport: {str(e)}")
        sys.exit(1)
    
    Path(export_manager.base_dir).mkdir(parents=True, exist_ok=True)
    
    results = {}
    
    # Export each subscription individually and push immediately after
    for sub in subscriptions:
        subscription_id = sub.get('id')
        subscription_name = sub.get('name', subscription_id)
        environment = sub.get('environment', 'unknown')
        
        # Check if subscription should be excluded
        export_enabled = sub.get('export_enabled', True)  # Default to True
        is_in_exclude_list = subscription_id in exclude_subscriptions
        
        if not export_enabled:
            logger.info(f"Skipping subscription {subscription_id} (export_enabled: false)")
            continue
        
        if is_in_exclude_list:
            logger.info(f"Skipping subscription {subscription_id} (in exclude_subscriptions list)")
            continue
        
        # Track timing for this subscription
        start_time = datetime.utcnow()
        subscription_result = None
        git_push_status = "skipped"
        error_message = None
        
        try:
            logger.info("")
            logger.info("=" * 70)
            logger.info(f"Processing subscription: {subscription_name}")
            logger.info("=" * 70)
            
            # Export subscription
            subscription_result = export_manager.export_subscription(sub, create_rg_folders)
            results[subscription_id] = subscription_result
            
            end_time = datetime.utcnow()
            
            # Determine status
            if subscription_result.get('successful_rgs', 0) > 0:
                status = "success"
            elif subscription_result.get('error'):
                status = "failed"
                error_message = subscription_result.get('error')
            else:
                status = "failed" if subscription_result.get('failed_rgs', 0) > 0 else "success"
            
            # Push to git if enabled and there are successful exports
            if push_to_repos and subscription_result.get('successful_rgs', 0) > 0:
                logger.info("")
                logger.info("=" * 70)
                logger.info(f"Pushing {subscription_name} to Git Repository")
                logger.info("=" * 70)
                
                sub_dir = Path(export_manager.base_dir) / export_manager._sanitize_name(subscription_name)
                
                if sub_dir.exists():
                    try:
                        success = export_manager.push_subscription_to_git(sub, sub_dir)
                        if success:
                            logger.success(f"Successfully pushed {subscription_name}")
                            git_push_status = "success"
                        else:
                            logger.error(f"Failed to push {subscription_name}")
                            git_push_status = "failed"
                    except Exception as e:
                        logger.error(f"Error pushing {subscription_name}: {str(e)}")
                        git_push_status = "failed"
                        error_message = str(e) if not error_message else f"{error_message}; Git push error: {str(e)}"
                else:
                    logger.warning(f"Export directory not found for {subscription_name}: {sub_dir}")
                    git_push_status = "failed"
            elif push_to_repos:
                logger.info(f"Skipping git push for {subscription_name} (no successful exports)")
            
            # Send to Log Analytics (wrapped in try-except to prevent failures from affecting export result)
            try:
                log_analytics.send_subscription_backup_status(
                    subscription_id=subscription_id,
                    subscription_name=subscription_name,
                    environment=environment,
                    status=status,
                    start_time=start_time,
                    end_time=end_time,
                    total_resource_groups=subscription_result.get('total_rgs', 0),
                    successful_resource_groups=subscription_result.get('successful_rgs', 0),
                    failed_resource_groups=subscription_result.get('failed_rgs', 0),
                    git_push_status=git_push_status,
                    error_message=error_message
                )
            except Exception as la_error:
                # Log Analytics failure should not affect export result
                logger.warning(f"Failed to send data to Log Analytics for {subscription_name}: {str(la_error)}")
                logger.info("Export result is preserved despite Log Analytics failure")
            
        except Exception as e:
            end_time = datetime.utcnow()
            error_message = str(e)
            logger.error(f"Fatal error exporting subscription {subscription_id}: {error_message}")
            import traceback
            traceback.print_exc()
            
            results[subscription_id] = {
                'subscription_id': subscription_id,
                'subscription_name': subscription_name,
                'error': error_message
            }
            
            # Send failure to Log Analytics (wrapped in try-except to prevent double failure)
            try:
                log_analytics.send_subscription_backup_status(
                    subscription_id=subscription_id,
                    subscription_name=subscription_name,
                    environment=environment,
                    status="failed",
                    start_time=start_time,
                    end_time=end_time,
                    total_resource_groups=0,
                    successful_resource_groups=0,
                    failed_resource_groups=0,
                    git_push_status="skipped",
                    error_message=error_message
                )
            except Exception as la_error:
                logger.warning(f"Failed to send failure status to Log Analytics for {subscription_name}: {str(la_error)}")
            
            # Continue with next subscription instead of exiting
            logger.warning(f"Continuing with next subscription after error in {subscription_name}")
    
    if not results:
        logger.error("No subscriptions were exported. Check your configuration.")
        sys.exit(1)
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("Export Summary")
    logger.info("=" * 70)
    
    total_subs = len(results)
    successful_subs = sum(1 for r in results.values() if r.get('successful_rgs', 0) > 0)
    total_rgs = sum(r.get('total_rgs', 0) for r in results.values())
    successful_rgs = sum(r.get('successful_rgs', 0) for r in results.values())
    
    logger.info(f"Subscriptions processed: {total_subs}")
    logger.info(f"Subscriptions with successful exports: {successful_subs}")
    logger.info(f"Total resource groups: {total_rgs}")
    logger.info(f"Successfully exported: {successful_rgs}")
    logger.info(f"Failed: {total_rgs - successful_rgs}")
    
    results_file = Path(export_manager.base_dir) / 'export_results.json'
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    logger.success(f"Export results saved to: {results_file}")
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("Export completed!")
    logger.info("=" * 70)
    logger.info(f"Output directory: {export_manager.base_dir}")
    logger.info("")
    logger.info("Next steps:")
    logger.info("1. Review exported Terraform code in the output directory")
    logger.info("2. Test with: terraform init && terraform plan")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger = get_logger()
        logger.info("")
        logger.info("Export cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger = get_logger()
        logger.error("")
        logger.error(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


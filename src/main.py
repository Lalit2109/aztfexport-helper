"""
Main script to orchestrate Azure resource export to Terraform
"""

import os
import sys
import json
import subprocess
import argparse
from pathlib import Path
from typing import Dict, Any
from dotenv import load_dotenv

from export_manager import ExportManager
from logger import get_logger


def export_single_subscription(export_manager: ExportManager, subscription_id: str) -> Dict[str, Any]:
    """Export a single subscription by ID"""
    logger = get_logger()
    subscriptions = export_manager.config.get('subscriptions', [])
    
    # Find the subscription in config
    subscription = None
    for sub in subscriptions:
        if sub.get('id') == subscription_id:
            subscription = sub
            break
    
    if not subscription:
        logger.error(f"Subscription {subscription_id} not found in configuration")
        return {
            'subscription_id': subscription_id,
            'subscription_name': 'Unknown',
            'error': f'Subscription {subscription_id} not found in configuration'
        }
    
    if not subscription.get('export_enabled', True):
        logger.info(f"Subscription {subscription_id} is disabled, skipping")
        return {
            'subscription_id': subscription_id,
            'subscription_name': subscription.get('name', subscription_id),
            'error': 'Export disabled for this subscription'
        }
    
    # Export the subscription
    try:
        create_rg_folders = export_manager.config.get('output', {}).get('create_rg_folders', True)
        result = export_manager.export_subscription(subscription, create_rg_folders)
        
        # Push to git if enabled and export was successful
        push_to_repos = os.getenv('PUSH_TO_REPOS', 'false').lower() == 'true'
        push_to_repos = push_to_repos or export_manager.config.get('git', {}).get('push_to_repos', False)
        
        if push_to_repos and result.get('successful_rgs', 0) > 0:
            subscription_name = subscription.get('name', subscription_id)
            sub_dir = Path(export_manager.base_dir) / export_manager._sanitize_name(subscription_name)
            
            if sub_dir.exists():
                logger.info(f"Pushing {subscription_name} to repository...")
                try:
                    success = export_manager.push_subscription_to_git(subscription, sub_dir)
                    if success:
                        logger.success(f"Successfully pushed {subscription_name}")
                        result['git_push'] = 'success'
                    else:
                        logger.error(f"Failed to push {subscription_name}")
                        result['git_push'] = 'failed'
                except Exception as e:
                    logger.error(f"Error pushing {subscription_name}: {str(e)}")
                    result['git_push'] = 'error'
                    result['git_push_error'] = str(e)
            else:
                logger.warning(f"Export directory not found for {subscription_name}: {sub_dir}")
                result['git_push'] = 'skipped'
        
        return result
    except Exception as e:
        logger.error(f"Error exporting subscription {subscription_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'subscription_id': subscription_id,
            'subscription_name': subscription.get('name', subscription_id),
            'error': str(e)
        }


def main():
    """Main execution function"""
    load_dotenv()
    logger = get_logger()
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Export Azure resources to Terraform')
    parser.add_argument('--subscription-id', type=str, help='Export only this subscription ID (for parallel execution)')
    args = parser.parse_args()
    
    config_path = os.getenv('CONFIG_PATH', 'config/subscriptions.yaml')
    
    logger.info("=" * 70)
    logger.info("Azure Infrastructure Export to Terraform")
    logger.info("Using aztfexport for resource export")
    if args.subscription_id:
        logger.info(f"Single subscription mode: {args.subscription_id}")
    else:
        logger.info("All subscriptions mode")
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
    
    # Single subscription mode (for parallel execution)
    if args.subscription_id:
        try:
            result = export_single_subscription(export_manager, args.subscription_id)
            results = {args.subscription_id: result}
        except Exception as e:
            logger.error(f"Fatal error during export: {str(e)}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    else:
        # All subscriptions mode (backward compatibility)
        try:
            results = export_manager.export_all_subscriptions()
        except Exception as e:
            logger.error(f"Fatal error during export: {str(e)}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
        
        if not results:
            logger.error("No subscriptions were exported. Check your configuration.")
            sys.exit(1)
        
        # Only push to git if export was successful (for all subscriptions mode)
        push_to_repos = os.getenv('PUSH_TO_REPOS', 'false').lower() == 'true'
        push_to_repos = push_to_repos or export_manager.config.get('git', {}).get('push_to_repos', False)
        
        if push_to_repos:
            # Check if any exports were successful
            total_successful = sum(r.get('successful_rgs', 0) for r in results.values())
            
            if total_successful == 0:
                logger.warning("No successful exports found. Skipping git push.")
            else:
                logger.info("")
                logger.info("=" * 70)
                logger.info("Pushing to Git Repositories")
                logger.info("=" * 70)
                
                subscriptions = export_manager.config.get('subscriptions', [])
                
                for sub in subscriptions:
                    if not sub.get('export_enabled', True):
                        continue
                    
                    subscription_id = sub.get('id')
                    subscription_result = results.get(subscription_id)
                    
                    # Only push if this subscription had successful exports
                    if subscription_result and subscription_result.get('successful_rgs', 0) > 0:
                        subscription_name = sub.get('name', sub.get('id'))
                        sub_dir = Path(export_manager.base_dir) / export_manager._sanitize_name(subscription_name)
                        
                        if sub_dir.exists():
                            logger.info(f"Pushing {subscription_name} to repository...")
                            try:
                                success = export_manager.push_subscription_to_git(sub, sub_dir)
                                if success:
                                    logger.success(f"Successfully pushed {subscription_name}")
                                else:
                                    logger.error(f"Failed to push {subscription_name}")
                            except Exception as e:
                                logger.error(f"Error pushing {subscription_name}: {str(e)}")
                        else:
                            logger.warning(f"Export directory not found for {subscription_name}: {sub_dir}")
                    else:
                        subscription_name = sub.get('name', sub.get('id'))
                        logger.info(f"Skipping git push for {subscription_name} (no successful exports)")
    
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


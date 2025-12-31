"""
Main script to orchestrate Azure resource export to Terraform
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

from core.export import ExportService
from core.git import GitService
from core.log_analytics import LogAnalyticsSender
from core.logger import get_logger
from core.config import load_config


def main():
    """Main execution function"""
    load_dotenv()
    logger = get_logger()
    
    subscription_id = os.getenv('SUBSCRIPTION_ID')
    subscription_name = os.getenv('SUBSCRIPTION_NAME')
    config_path = os.getenv('CONFIG_PATH', 'config/subscriptions.yaml')
    
    if not subscription_id:
        logger.error("SUBSCRIPTION_ID environment variable is required")
        logger.info("Please set SUBSCRIPTION_ID before running the script")
        sys.exit(1)
    
    if not subscription_name:
        subscription_name = subscription_id
        logger.info(f"SUBSCRIPTION_NAME not set, using subscription ID as name: {subscription_name}")
    
    logger.info("=" * 70)
    logger.info("Azure Infrastructure Export to Terraform")
    logger.info("Using aztfexport for resource export")
    logger.info("=" * 70)
    logger.info("")
    logger.info(f"Subscription ID: {subscription_id}")
    logger.info(f"Subscription Name: {subscription_name}")
    logger.info("")
    
    try:
        config = load_config(config_path)
    except FileNotFoundError as e:
        logger.error(f"Configuration file not found: {config_path}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error loading configuration: {str(e)}")
        sys.exit(1)
    
    output_dir = os.getenv('OUTPUT_DIR') or config.get('output', {}).get('base_dir', './exports')
    
    export_service = ExportService(
        subscription_id=subscription_id,
        subscription_name=subscription_name,
        config_path=config_path,
        output_dir=output_dir
    )
    
    logger.info("Checking disk space...")
    if not export_service.check_disk_space(min_free_percent=5.0):
        logger.warning("⚠️  Low disk space detected. Consider cleaning up old exports.")
        logger.warning("   Continuing anyway, but exports may fail if disk fills up.")
        logger.info("")
    
    Path(export_service.base_dir).mkdir(parents=True, exist_ok=True)
    
    start_time = datetime.utcnow()
    subscription_result = None
    git_push_status = "skipped"
    error_message = None
    
    try:
        logger.info("")
        logger.info("=" * 70)
        logger.info(f"Processing subscription: {subscription_name}")
        logger.info("=" * 70)
        
        subscription_result = export_service.export_subscription()
        end_time = datetime.utcnow()
        
        if subscription_result.get('successful_rgs', 0) > 0:
            status = "success"
        elif subscription_result.get('error'):
            status = "failed"
            error_message = subscription_result.get('error')
        else:
            status = "failed" if subscription_result.get('failed_rgs', 0) > 0 else "success"
        
        push_to_repos = os.getenv('PUSH_TO_REPOS', 'false').lower() == 'true'
        push_to_repos = push_to_repos or config.get('git', {}).get('push_to_repos', False)
        
        if push_to_repos and subscription_result.get('successful_rgs', 0) > 0:
            logger.info("")
            logger.info("=" * 70)
            logger.info(f"Pushing {subscription_name} to Git Repository")
            logger.info("=" * 70)
            
            sub_dir = Path(export_service.base_dir) / export_service._sanitize_name(subscription_name)
            
            if sub_dir.exists():
                try:
                    git_service = GitService(config)
                    subscription_dict = {
                        'id': subscription_id,
                        'name': subscription_name
                    }
                    success = git_service.push_to_repo(subscription_dict, sub_dir)
                    if success:
                        logger.success(f"Successfully pushed {subscription_name}")
                        git_push_status = "success"
                        
                        cleanup_after_push = config.get('output', {}).get('cleanup_after_push', True)
                        if cleanup_after_push:
                            logger.info(f"Cleaning up export directory for {subscription_name}...")
                            try:
                                import shutil
                                shutil.rmtree(sub_dir)
                                logger.info(f"Cleaned up export directory: {sub_dir}")
                            except Exception as e:
                                logger.warning(f"Failed to cleanup export directory: {str(e)}")
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
        
        try:
            log_analytics = LogAnalyticsSender()
            log_analytics.send_subscription_backup_status(
                subscription_id=subscription_id,
                subscription_name=subscription_name,
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
            logger.warning(f"Failed to send data to Log Analytics for {subscription_name}: {str(la_error)}")
        
    except Exception as e:
        end_time = datetime.utcnow()
        error_message = str(e)
        logger.error(f"Fatal error exporting subscription {subscription_id}: {error_message}")
        import traceback
        traceback.print_exc()
        
        subscription_result = {
            'subscription_id': subscription_id,
            'subscription_name': subscription_name,
            'error': error_message
        }
        
        try:
            log_analytics = LogAnalyticsSender()
            log_analytics.send_subscription_backup_status(
                subscription_id=subscription_id,
                subscription_name=subscription_name,
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
        
        sys.exit(1)
    
    if not subscription_result:
        logger.error("Export failed. Check the logs above for details.")
        sys.exit(1)
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("Export Summary")
    logger.info("=" * 70)
    
    total_rgs = subscription_result.get('total_rgs', 0)
    successful_rgs = subscription_result.get('successful_rgs', 0)
    
    logger.info(f"Total resource groups: {total_rgs}")
    logger.info(f"Successfully exported: {successful_rgs}")
    logger.info(f"Failed: {total_rgs - successful_rgs}")
    
    results_file = Path(export_service.base_dir) / 'export_results.json'
    with open(results_file, 'w') as f:
        json.dump(subscription_result, f, indent=2, default=str)
    logger.success(f"Export results saved to: {results_file}")
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("Export completed!")
    logger.info("=" * 70)
    logger.info(f"Output directory: {export_service.base_dir}")
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

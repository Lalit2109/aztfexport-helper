"""
Main script to orchestrate Azure resource export to Terraform
"""

import os
import sys
import json
import yaml
import subprocess
from pathlib import Path
from dotenv import load_dotenv

from export_manager import ExportManager


def main():
    """Main execution function"""
    # Load environment variables
    load_dotenv()
    
    # Get configuration
    config_path = os.getenv('CONFIG_PATH', 'config/subscriptions.yaml')
    
    print("=" * 70)
    print("Azure Infrastructure Export to Terraform")
    print("Using aztfexport for resource export")
    print("=" * 70)
    print()
    
    # Initialize export manager (this will find Azure CLI path)
    export_manager = ExportManager(config_path)
    
    # Verify Azure CLI authentication using the path found by ExportManager
    print("Checking Azure CLI authentication...")
    az_cli_path = export_manager.az_cli_path
    
    if az_cli_path != 'az' and not os.path.exists(az_cli_path):
        print(f"✗ Azure CLI not found at expected path: {az_cli_path}")
        print("  Please ensure Azure CLI is installed and in your PATH")
        sys.exit(1)
    
    try:
        # Check if Azure CLI is available and logged in
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
                print(f"✓ Azure CLI is authenticated")
                print(f"  Account: {account.get('name', 'N/A')}")
                print(f"  Subscription ID: {account.get('id', 'N/A')}")
            else:
                print("⚠️  Could not get account information")
        else:
            print("✗ Not logged in to Azure CLI")
            print("  Please run: az login")
            sys.exit(1)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("✗ Azure CLI not found")
        print("  Please install Azure CLI: https://docs.microsoft.com/cli/azure/install-azure-cli")
        sys.exit(1)
    except Exception as e:
        print(f"⚠️  Error checking Azure CLI: {str(e)}")
        print("  Continuing anyway...")
    
    print()
    
    # Export resources
    print("Exporting Azure resources...")
    print("-" * 70)
    
    try:
        results = export_manager.export_all_subscriptions()
    except Exception as e:
        print(f"\n✗ Fatal error during export: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    if not results:
        print("\nNo subscriptions were exported. Check your configuration.")
        sys.exit(1)
    
    # Print summary
    print("\n" + "=" * 70)
    print("Export Summary")
    print("=" * 70)
    
    total_subs = len(results)
    successful_subs = sum(1 for r in results.values() if r.get('successful_rgs', 0) > 0)
    total_rgs = sum(r.get('total_rgs', 0) for r in results.values())
    successful_rgs = sum(r.get('successful_rgs', 0) for r in results.values())
    
    print(f"Subscriptions processed: {total_subs}")
    print(f"Subscriptions with successful exports: {successful_subs}")
    print(f"Total resource groups: {total_rgs}")
    print(f"Successfully exported: {successful_rgs}")
    print(f"Failed: {total_rgs - successful_rgs}")
    
    # Save results to JSON
    results_file = Path(export_manager.base_dir) / 'export_results.json'
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n✓ Export results saved to: {results_file}")
    
    print("\n" + "=" * 70)
    print("Export completed!")
    print("=" * 70)
    print(f"\nOutput directory: {export_manager.base_dir}")
    print("\nNext steps:")
    print("1. Review exported Terraform code in the output directory")
    print("2. Test with: terraform init && terraform plan")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nExport cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nError: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


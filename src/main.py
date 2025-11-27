"""
Main script to orchestrate Azure resource export and git operations
"""

import os
import sys
import json
import yaml
from pathlib import Path
from dotenv import load_dotenv

from export_manager import ExportManager
from git_manager import GitManager


def main():
    """Main execution function"""
    # Load environment variables
    load_dotenv()
    
    # Get configuration
    config_path = os.getenv('CONFIG_PATH', 'config/subscriptions.yaml')
    
    # Load config to check git push setting
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Check git push flag - environment variable overrides config file
    push_to_repos_env = os.getenv('PUSH_TO_REPOS', '').lower()
    if push_to_repos_env in ['true', 'false']:
        push_to_repos = push_to_repos_env == 'true'
    else:
        # Use config file setting (default: false)
        push_to_repos = config.get('git', {}).get('push_to_repos', False)
    
    git_branch = os.getenv('GIT_BRANCH') or config.get('git', {}).get('branch', 'main')
    
    print("=" * 70)
    print("Azure Infrastructure Export to Terraform")
    print("Using aztfexport for resource export")
    print("=" * 70)
    print()
    
    # Check available authentication methods
    print("Checking Azure authentication...")
    auth_method = None
    account_info = None
    
    # Try to detect which authentication method will be used
    try:
        import subprocess
        # Check if Azure CLI is available and logged in
        result = subprocess.run(
            ['az', 'account', 'show'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            auth_method = "Azure CLI"
            account_info = subprocess.run(
                ['az', 'account', 'show', '--query', '{name:name, id:id}', '-o', 'json'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if account_info.returncode == 0:
                import json
                account = json.loads(account_info.stdout)
                print(f"✓ Will use Azure CLI credentials")
                print(f"  Account: {account.get('name', 'N/A')}")
                print(f"  Subscription ID: {account.get('id', 'N/A')}")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        # Azure CLI not available, will try other methods
        pass
    except Exception:
        pass
    
    # Check for service principal environment variables
    if not auth_method:
        if os.getenv('AZURE_CLIENT_ID') and os.getenv('AZURE_CLIENT_SECRET') and os.getenv('AZURE_TENANT_ID'):
            auth_method = "Service Principal (from environment variables)"
            print(f"✓ Will use Service Principal credentials from environment variables")
            print(f"  Client ID: {os.getenv('AZURE_CLIENT_ID')[:8]}...")
        else:
            # DefaultAzureCredential will try multiple methods automatically
            auth_method = "DefaultAzureCredential (automatic detection)"
            print(f"✓ Will use DefaultAzureCredential - automatically detecting available credentials")
            print(f"  This will try: Azure CLI → Managed Identity → Environment Variables → etc.")
    
    print()
    
    # Initialize managers
    export_manager = ExportManager(config_path)
    git_manager = GitManager(export_manager.base_dir)
    
    # Step 1: Export resources
    print("Step 1: Exporting Azure resources...")
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
    
    # Step 2: Push to repositories (if enabled)
    if push_to_repos:
        print("\n" + "=" * 70)
        print("Step 2: Pushing to Azure DevOps repositories...")
        print("-" * 70)
        print("⚠️  Git push is ENABLED - changes will be pushed to repositories")
        print()
        
        config = export_manager.config
        subscriptions = config.get('subscriptions', [])
        
        push_results = git_manager.push_all_repos(
            subscriptions,
            Path(export_manager.base_dir),
            git_branch
        )
        
        print("\n" + "=" * 70)
        print("Push Summary")
        print("=" * 70)
        
        successful_pushes = sum(1 for v in push_results.values() if v)
        print(f"Repositories pushed: {successful_pushes}/{len(push_results)}")
        
        for sub_id, success in push_results.items():
            sub_name = next(
                (s['name'] for s in subscriptions if s['id'] == sub_id),
                sub_id
            )
            status = "✓" if success else "✗"
            print(f"  {status} {sub_name}")
    else:
        print("\n" + "=" * 70)
        print("Step 2: Git Push - SKIPPED")
        print("=" * 70)
        print("\n✓ Export completed successfully!")
        print("  Git push is disabled - exported code is in local directory only")
        print(f"  Review exported code in: {export_manager.base_dir}")
        print("\nTo enable pushing to repositories after verification:")
        print("  Option 1: Edit config/subscriptions.yaml")
        print("    Set: git.push_to_repos: true")
        print("\n  Option 2: Use environment variable (overrides config):")
        print("    export PUSH_TO_REPOS=true")
        print("    python src/main.py")
    
    print("\n" + "=" * 70)
    print("Export completed!")
    print("=" * 70)
    print(f"\nOutput directory: {export_manager.base_dir}")
    print("\nNext steps:")
    print("1. Review exported Terraform code in the output directory")
    print("2. Test with: terraform init && terraform plan")
    if not push_to_repos:
        print("3. After verification, enable git push:")
        print("   - Edit config/subscriptions.yaml: set git.push_to_repos: true")
        print("   - Or use: export PUSH_TO_REPOS=true && python src/main.py")
    else:
        print("3. ✓ Code has been pushed to repositories")


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


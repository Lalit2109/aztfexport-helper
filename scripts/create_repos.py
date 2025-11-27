"""
Helper script to create Azure DevOps repositories if they don't exist
"""

import os
import sys
import yaml
import requests
from typing import Dict, Any, List


def create_azure_devops_repo(
    organization: str,
    project: str,
    repo_name: str,
    pat_token: str
) -> bool:
    """Create a repository in Azure DevOps"""
    url = f"https://dev.azure.com/{organization}/{project}/_apis/git/repositories?api-version=7.1"
    
    headers = {
        'Authorization': f'Basic {pat_token}',
        'Content-Type': 'application/json'
    }
    
    data = {
        'name': repo_name,
        'project': {
            'id': project
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, auth=('', pat_token))
        
        if response.status_code == 201:
            print(f"  ✓ Created repository: {repo_name}")
            return True
        elif response.status_code == 409:
            print(f"  ⚠️  Repository already exists: {repo_name}")
            return True
        else:
            print(f"  ✗ Failed to create repository {repo_name}: {response.status_code}")
            print(f"    {response.text}")
            return False
    except Exception as e:
        print(f"  ✗ Error creating repository {repo_name}: {str(e)}")
        return False


def main():
    """Main function"""
    import base64
    
    # Load config
    config_path = sys.argv[1] if len(sys.argv) > 1 else 'config/subscriptions.yaml'
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Get Azure DevOps config
    ado_config = config.get('azure_devops', {})
    organization = ado_config.get('organization')
    project = ado_config.get('project')
    
    if not organization or not project:
        print("Error: Azure DevOps organization and project must be configured")
        print("Edit config/subscriptions.yaml and set azure_devops.organization and azure_devops.project")
        sys.exit(1)
    
    # Get PAT token
    pat_token = os.getenv('AZURE_DEVOPS_PAT')
    if not pat_token:
        print("Error: AZURE_DEVOPS_PAT environment variable not set")
        print("Set it with: export AZURE_DEVOPS_PAT=your-token")
        sys.exit(1)
    
    # Encode PAT for basic auth
    pat_encoded = base64.b64encode(f':{pat_token}'.encode()).decode()
    
    print("=" * 60)
    print("Creating Azure DevOps Repositories")
    print("=" * 60)
    print(f"Organization: {organization}")
    print(f"Project: {project}")
    print()
    
    subscriptions = config.get('subscriptions', [])
    created = 0
    existing = 0
    failed = 0
    
    for sub in subscriptions:
        if not sub.get('export_enabled', True):
            continue
        
        repo_name = sub.get('repo_name')
        if not repo_name:
            print(f"⚠️  No repo_name for subscription {sub['id']}, skipping")
            continue
        
        print(f"Processing: {sub['name']} -> {repo_name}")
        
        # Check if repo URL is provided, extract repo name if needed
        repo_url = sub.get('repo_url', '')
        if repo_url and repo_name not in repo_url:
            # Try to extract repo name from URL
            if '/_git/' in repo_url:
                repo_name = repo_url.split('/_git/')[-1]
        
        success = create_azure_devops_repo(
            organization,
            project,
            repo_name,
            pat_encoded
        )
        
        if success:
            if 'already exists' in str(success):
                existing += 1
            else:
                created += 1
        else:
            failed += 1
    
    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Created: {created}")
    print(f"Already existed: {existing}")
    print(f"Failed: {failed}")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nError: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


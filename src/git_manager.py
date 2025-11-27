"""
Git Repository Manager
Handles git operations for pushing exported Terraform code to Azure DevOps repos
"""

import os
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
import git
from git import Repo, Remote
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


class GitManager:
    """Manages git operations for Terraform repositories"""
    
    def __init__(self, base_dir: str = "./exports", prefer_ssh: bool = True):
        """Initialize git manager"""
        self.base_dir = Path(base_dir)
        self.git_username = os.getenv('GIT_USERNAME', 'azure-pipelines')
        self.git_email = os.getenv('GIT_EMAIL', 'azure-pipelines@devops.com')
        # Prefer SSH URLs (uses local SSH credentials) over HTTPS with tokens
        self.prefer_ssh = os.getenv('GIT_PREFER_SSH', '').lower() in ['true', '1', 'yes'] if os.getenv('GIT_PREFER_SSH') else prefer_ssh
        
    def _setup_git_config(self):
        """Configure git user name and email"""
        try:
            subprocess.run(
                ['git', 'config', '--global', 'user.name', self.git_username],
                check=True,
                capture_output=True
            )
            subprocess.run(
                ['git', 'config', '--global', 'user.email', self.git_email],
                check=True,
                capture_output=True
            )
        except subprocess.CalledProcessError as e:
            print(f"Warning: Could not set git config: {e}")
    
    def _get_azure_devops_token(self) -> Optional[str]:
        """Get Azure DevOps PAT from environment"""
        # In Azure DevOps pipelines, use System.AccessToken
        token = os.getenv('SYSTEM_ACCESS_TOKEN') or os.getenv('AZURE_DEVOPS_PAT')
        return token
    
    def _create_azure_devops_repo(
        self,
        organization: str,
        project: str,
        repo_name: str
    ) -> bool:
        """Create a repository in Azure DevOps if it doesn't exist"""
        if not REQUESTS_AVAILABLE:
            print(f"  ⚠️  'requests' library not available, cannot create repository")
            print(f"    💡 Install with: pip install requests")
            return False
        
        token = self._get_azure_devops_token()
        if not token:
            print(f"  ⚠️  No Azure DevOps token found, cannot create repository")
            return False
        
        import base64
        
        url = f"https://dev.azure.com/{organization}/{project}/_apis/git/repositories?api-version=7.1"
        
        # Encode PAT for basic auth
        pat_encoded = base64.b64encode(f':{token}'.encode()).decode()
        
        headers = {
            'Authorization': f'Basic {pat_encoded}',
            'Content-Type': 'application/json'
        }
        
        data = {
            'name': repo_name,
            'project': {
                'id': project
            }
        }
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 201:
                print(f"  ✓ Created repository: {repo_name}")
                return True
            elif response.status_code == 409:
                print(f"  ✓ Repository already exists: {repo_name}")
                return True
            else:
                error_msg = response.text
                print(f"  ⚠️  Could not create repository {repo_name}: {response.status_code}")
                if response.status_code == 401 or response.status_code == 403:
                    print(f"    💡 Check your Azure DevOps PAT token permissions")
                return False
        except requests.exceptions.RequestException as e:
            print(f"  ⚠️  Error creating repository {repo_name}: {str(e)}")
            return False
        except Exception as e:
            print(f"  ⚠️  Unexpected error creating repository: {str(e)}")
            return False
    
    def _is_ssh_url(self, repo_url: str) -> bool:
        """Check if URL is SSH format"""
        return repo_url.startswith('ssh://') or repo_url.startswith('git@')
    
    def _convert_https_to_ssh(self, repo_url: str) -> str:
        """Convert Azure DevOps HTTPS URL to SSH format"""
        if 'dev.azure.com' in repo_url and '/_git/' in repo_url:
            # Extract: https://dev.azure.com/{org}/{project}/_git/{repo}
            # Convert to: git@ssh.dev.azure.com:v3/{org}/{project}/{repo}
            if repo_url.startswith('https://'):
                url_part = repo_url.replace('https://', '')
            elif repo_url.startswith('http://'):
                url_part = repo_url.replace('http://', '')
            else:
                return repo_url
            
            # Remove any existing authentication
            if '@' in url_part:
                url_part = url_part.split('@', 1)[1]
            
            # Parse: dev.azure.com/{org}/{project}/_git/{repo}
            parts = url_part.split('/')
            if len(parts) >= 4 and parts[0] == 'dev.azure.com':
                org = parts[1]
                project = parts[2]
                repo = parts[4] if len(parts) > 4 else parts[3]
                return f"git@ssh.dev.azure.com:v3/{org}/{project}/{repo}"
        
        return repo_url
    
    def _prepare_repo_url(self, repo_url: str, token: Optional[str] = None, prefer_ssh: Optional[bool] = None) -> str:
        """Prepare repository URL with authentication or convert to SSH"""
        # Use instance preference if not explicitly provided
        if prefer_ssh is None:
            prefer_ssh = self.prefer_ssh
        
        # If already SSH, use as-is
        if self._is_ssh_url(repo_url):
            print(f"  ✓ Using SSH URL (credentials from SSH agent)")
            return repo_url
        
        # If prefer_ssh is True and it's an Azure DevOps HTTPS URL, convert to SSH
        if prefer_ssh and 'dev.azure.com' in repo_url:
            ssh_url = self._convert_https_to_ssh(repo_url)
            if ssh_url != repo_url:
                print(f"  ✓ Converted HTTPS URL to SSH format")
                print(f"    SSH URL: {ssh_url}")
                return ssh_url
        
        # Otherwise, use HTTPS with token authentication
        if not token:
            token = self._get_azure_devops_token()
        
        if token and 'dev.azure.com' in repo_url:
            # Insert token into URL: https://{token}@dev.azure.com/...
            if repo_url.startswith('https://'):
                # Extract the part after https://
                url_part = repo_url.replace('https://', '')
                return f"https://{token}@{url_part}"
            elif repo_url.startswith('http://'):
                url_part = repo_url.replace('http://', '')
                return f"http://{token}@{url_part}"
        
        return repo_url
    
    def _create_gitignore(self, repo_path: Path):
        """Create .gitignore file for Terraform repository"""
        gitignore_content = """# Terraform directories and lock files (excluded)
.terraform/
.terraform.lock.hcl
terraform.tfstate.d/

# Terraform variable files (may contain sensitive data)
*.tfvars
*.tfvars.backup
*.auto.tfvars
*.auto.tfvars.json

# Crash log files
crash.log
crash.*.log

# Ignore override files
override.tf
override.tf.json
*_override.tf
*_override.tf.json

# Ignore CLI configuration files
.terraformrc
terraform.rc

# Ignore Mac files
.DS_Store

# Ignore export results
export_results.json

# Note: Terraform state files (*.tfstate) are INCLUDED in this repository
# State files are tracked for version control and backup purposes
"""
        gitignore_path = repo_path / '.gitignore'
        if not gitignore_path.exists():
            gitignore_path.write_text(gitignore_content)
            print(f"  ✓ Created .gitignore file")
        else:
            # Update existing .gitignore to ensure state files are not excluded
            existing_content = gitignore_path.read_text()
            # Remove state file exclusions if present
            updated_content = existing_content
            if '*.tfstate' in existing_content or '*.tfstate.*' in existing_content:
                # Remove lines that exclude state files
                lines = existing_content.split('\n')
                filtered_lines = []
                for line in lines:
                    if not (line.strip().startswith('*.tfstate') or 
                            line.strip().startswith('#') and 'tfstate' in line.lower() and 'exclude' in line.lower()):
                        filtered_lines.append(line)
                updated_content = '\n'.join(filtered_lines)
                # Add note about state files if not present
                if '# Note: Terraform state files' not in updated_content:
                    updated_content += '\n\n# Note: Terraform state files (*.tfstate) are INCLUDED in this repository\n'
                gitignore_path.write_text(updated_content)
                print(f"  ✓ Updated .gitignore file (state files will be included)")
    
    def _create_readme(self, repo_path: Path, subscription: Dict[str, Any]):
        """Create README.md for the repository"""
        subscription_name = subscription.get('name', 'Unknown')
        subscription_id = subscription.get('id', 'Unknown')
        environment = subscription.get('environment', 'Unknown')
        
        readme_content = f"""# Terraform Infrastructure as Code

This repository contains Terraform code for Azure infrastructure in **{subscription_name}**.

## Subscription Information

- **Subscription Name**: {subscription_name}
- **Subscription ID**: {subscription_id}
- **Environment**: {environment}

## Repository Structure

```
.
├── resource-group-1/          # Resource group exports
│   ├── main.tf
│   ├── providers.tf
│   └── ...
├── resource-group-2/
│   └── ...
└── README.md
```

## Usage

### Initialize Terraform

\`\`\`bash
cd resource-group-1
terraform init
\`\`\`

### Plan Changes

\`\`\`bash
terraform plan
\`\`\`

### Apply Changes

\`\`\`bash
terraform apply
\`\`\`

## Notes

- This code was automatically generated using aztfexport
- Review and test all changes before applying to production
- Ensure you have appropriate Azure permissions before running terraform apply

## Maintenance

This repository is automatically updated via Azure DevOps pipeline.
"""
        readme_path = repo_path / 'README.md'
        readme_path.write_text(readme_content)
        print(f"  ✓ Created README.md file")
    
    def initialize_repo(
        self,
        repo_path: Path,
        repo_url: Optional[str] = None,
        branch: str = 'main'
    ) -> bool:
        """Initialize or update a git repository"""
        try:
            repo_path = Path(repo_path).resolve()
            
            # Check if already a git repo
            if (repo_path / '.git').exists():
                print(f"  Repository already initialized: {repo_path.name}")
                repo = Repo(repo_path)
                
                # Check if remote exists
                if repo.remotes:
                    remote = repo.remotes.origin
                    if repo_url:
                        # Update remote URL if provided
                        if self._is_ssh_url(repo_url):
                            remote.set_url(repo_url)
                            print(f"  ✓ Updated remote URL (SSH)")
                        else:
                            auth_url = self._prepare_repo_url(repo_url, prefer_ssh=True)
                            remote.set_url(auth_url)
                            print(f"  ✓ Updated remote URL")
                else:
                    # Add remote if it doesn't exist
                    if repo_url:
                        if self._is_ssh_url(repo_url):
                            repo.create_remote('origin', repo_url)
                            print(f"  ✓ Added remote origin (SSH)")
                        else:
                            auth_url = self._prepare_repo_url(repo_url, prefer_ssh=True)
                            repo.create_remote('origin', auth_url)
                            print(f"  ✓ Added remote origin")
                    else:
                        print(f"  ⚠️  No remote URL provided for existing repo")
                
                return True
            
            # Initialize new repository
            print(f"  Initializing git repository: {repo_path.name}")
            repo = Repo.init(repo_path)
            
            # Configure git
            self._setup_git_config()
            
            # Create .gitignore
            self._create_gitignore(repo_path)
            
            # Add remote if URL provided
            if repo_url:
                # Check if using SSH (no token needed)
                if self._is_ssh_url(repo_url):
                    # Use SSH URL as-is
                    repo.create_remote('origin', repo_url)
                    print(f"  ✓ Added remote origin (SSH)")
                else:
                    # Try to convert to SSH first (if prefer_ssh is enabled)
                    auth_url = self._prepare_repo_url(repo_url, prefer_ssh=True)
                    
                    # If still HTTPS and no token, warn but continue (might work with cached credentials)
                    if not self._is_ssh_url(auth_url):
                        token = self._get_azure_devops_token()
                        if not token:
                            print(f"  ⚠️  No Azure DevOps token found for HTTPS URL")
                            print(f"  💡 Options:")
                            print(f"     1. Use SSH URL format: git@ssh.dev.azure.com:v3/org/project/repo")
                            print(f"     2. Set AZURE_DEVOPS_PAT or SYSTEM_ACCESS_TOKEN environment variable")
                            # Still try to add remote - might work with cached credentials
                    
                    repo.create_remote('origin', auth_url)
                    print(f"  ✓ Added remote origin")
            else:
                print(f"  ⚠️  No repo_url configured, repository will be local only")
            
            # Create initial commit if there are files
            if any(repo_path.iterdir()):
                repo.git.add(A=True)
                repo.index.commit('Initial commit: Terraform export')
                print(f"  ✓ Created initial commit")
            
            # Create and checkout branch
            try:
                repo.git.checkout('-b', branch)
                print(f"  ✓ Created and checked out branch: {branch}")
            except git.exc.GitCommandError:
                # Branch might already exist, just checkout
                repo.git.checkout(branch)
                print(f"  ✓ Checked out existing branch: {branch}")
            
            return True
            
        except Exception as e:
            print(f"  ✗ Error initializing repository: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    def commit_and_push(
        self,
        repo_path: Path,
        commit_message: str = "Update: Terraform export",
        branch: str = 'main',
        force: bool = False
    ) -> bool:
        """Commit changes and push to remote"""
        try:
            repo_path = Path(repo_path).resolve()
            
            if not (repo_path / '.git').exists():
                print(f"  ✗ Not a git repository: {repo_path}")
                return False
            
            repo = Repo(repo_path)
            
            # Ensure we're on the correct branch
            try:
                if repo.active_branch.name != branch:
                    repo.git.checkout(branch)
                    print(f"  ✓ Switched to branch: {branch}")
            except git.exc.GitCommandError:
                # Branch doesn't exist locally, create it
                repo.git.checkout('-b', branch)
                print(f"  ✓ Created and switched to branch: {branch}")
            
            # Check if there are changes
            repo.git.add(A=True)  # Stage all changes including untracked files
            
            # Check if there are actual changes to commit
            if repo.is_dirty() or repo.untracked_files:
                # Get list of changed files for logging
                changed_files = repo.git.diff('--name-only', 'HEAD')
                untracked = repo.untracked_files
                
                if changed_files or untracked:
                    # Commit
                    repo.index.commit(commit_message)
                    print(f"  ✓ Committed changes: {commit_message}")
                    if changed_files:
                        print(f"    Modified files: {len(changed_files.split())}")
                    if untracked:
                        print(f"    New files: {len(untracked)}")
                else:
                    print(f"  No changes to commit")
                    return True
            else:
                print(f"  No changes to commit")
                return True
            
            # Push to remote
            if repo.remotes:
                remote = repo.remotes.origin
                try:
                    # Check if remote branch exists
                    remote_refs = [ref.name for ref in remote.refs]
                    remote_branch = f'origin/{branch}'
                    
                    if force:
                        repo.git.push('origin', branch, force=True)
                        print(f"  ✓ Force pushed to remote: {branch}")
                    else:
                        # Try normal push first
                        try:
                            repo.git.push('origin', branch)
                            print(f"  ✓ Pushed to remote: {branch}")
                            return True
                        except git.exc.GitCommandError as e:
                            # If branch exists remotely, try to pull and merge
                            if remote_branch in remote_refs:
                                print(f"  ⚠️  Remote branch exists, pulling changes first...")
                                repo.git.pull('origin', branch, '--no-rebase', '--no-edit')
                                repo.git.push('origin', branch)
                                print(f"  ✓ Pulled and pushed successfully")
                                return True
                            else:
                                # New branch, push with upstream
                                repo.git.push('--set-upstream', 'origin', branch)
                                print(f"  ✓ Pushed new branch to remote: {branch}")
                                return True
                    
                    return True
                except git.exc.GitCommandError as e:
                    error_msg = str(e)
                    print(f"  ✗ Error pushing to remote: {error_msg}")
                    
                    # Check for authentication errors
                    if 'authentication' in error_msg.lower() or 'unauthorized' in error_msg.lower():
                        print(f"  💡 Authentication failed. Check your Azure DevOps PAT token")
                        print(f"     Set AZURE_DEVOPS_PAT or SYSTEM_ACCESS_TOKEN environment variable")
                    
                    # Check for permission errors
                    if 'permission' in error_msg.lower() or 'forbidden' in error_msg.lower():
                        print(f"  💡 Permission denied. Ensure you have 'Contribute' permission to the repository")
                    
                    return False
            else:
                print(f"  ⚠️  No remote configured, skipping push")
                return True
                
        except Exception as e:
            print(f"  ✗ Error in commit/push: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    def push_subscription_repo(
        self,
        subscription: Dict[str, Any],
        subscription_dir: Path,
        branch: str = 'main',
        config: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Push a subscription's repository to Azure DevOps"""
        subscription_name = subscription['name']
        repo_url = subscription.get('repo_url')
        repo_name = subscription.get('repo_name')
        
        # Get subscription-specific branch if configured
        subscription_branch = subscription.get('branch', branch)
        
        print(f"\nPushing repository for: {subscription_name}")
        print(f"  Repository: {subscription_dir.name}")
        print(f"  Branch: {subscription_branch}")
        
        if not repo_url:
            print(f"  ⚠️  No repo_url configured, skipping push")
            return False
        
        # Extract repo name from URL if not provided
        if not repo_name and repo_url:
            if '/_git/' in repo_url:
                repo_name = repo_url.split('/_git/')[-1]
            else:
                # Fallback: use subscription name sanitized
                repo_name = self._sanitize_name(subscription_name)
        
        # Create repository in Azure DevOps if it doesn't exist
        if config and REQUESTS_AVAILABLE:
            ado_config = config.get('azure_devops', {})
            organization = ado_config.get('organization')
            project = ado_config.get('project')
            
            if organization and project and repo_name:
                print(f"  Checking if repository exists: {repo_name}")
                self._create_azure_devops_repo(organization, project, repo_name)
        
        # Check if directory exists and has content
        if not subscription_dir.exists():
            print(f"  ✗ Directory does not exist: {subscription_dir}")
            return False
        
        # Check if there are any resource group folders
        rg_folders = [d for d in subscription_dir.iterdir() if d.is_dir() and not d.name.startswith('.')]
        if not rg_folders:
            print(f"  ⚠️  No resource groups exported, skipping push")
            return True
        
        print(f"  Found {len(rg_folders)} resource group(s) to push")
        
        # Create/update README
        self._create_readme(subscription_dir, subscription)
        
        # Initialize repo if needed
        if not self.initialize_repo(subscription_dir, repo_url, subscription_branch):
            return False
        
        # Commit and push
        commit_msg = f"Update: Terraform export for {subscription_name}"
        return self.commit_and_push(subscription_dir, commit_msg, subscription_branch)
    
    def push_all_repos(
        self,
        subscriptions: list,
        base_dir: Path,
        branch: str = 'main',
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, bool]:
        """Push all subscription repositories"""
        results = {}
        
        for sub in subscriptions:
            if not sub.get('export_enabled', True):
                continue
            
            subscription_name = sub['name']
            
            # Use default: base_dir / sanitized_subscription_name
            subscription_dir = base_dir / self._sanitize_name(subscription_name)
            
            if not subscription_dir.exists():
                print(f"\n⚠️  Directory not found: {subscription_dir}")
                results[sub['id']] = False
                continue
            
            # Get subscription-specific branch if configured
            subscription_branch = sub.get('branch', branch)
            
            success = self.push_subscription_repo(sub, subscription_dir, subscription_branch, config)
            results[sub['id']] = success
        
        return results
    
    def _sanitize_name(self, name: str) -> str:
        """Sanitize name for filesystem"""
        import re
        name = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
        return name.lower()


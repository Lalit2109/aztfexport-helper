"""
Git Manager for pushing exported Terraform code to Azure DevOps repositories
"""

import os
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import quote, urlparse
from logger import get_logger


class GitManager:
    """Manages Git operations for pushing Terraform exports to repositories"""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize Git Manager"""
        self.logger = get_logger()
        self.config = config
        self.azure_devops_config = config.get('azure_devops', {})
        self.git_config = config.get('git', {})
        
    def _get_repo_url(self, subscription: Dict[str, Any]) -> Optional[str]:
        """Get repository URL for a subscription using subscription name"""
        subscription_name = subscription.get('name')
        if not subscription_name:
            return None
        
        org = self.azure_devops_config.get('organization')
        project = self.azure_devops_config.get('project')
        
        if org and project:
            # Use original subscription name (don't sanitize) - Azure DevOps supports spaces
            # URL encoding will handle spaces and special characters properly
            encoded_org = quote(org, safe='')
            encoded_project = quote(project, safe='')
            encoded_repo = quote(subscription_name, safe='')  # Don't sanitize, just encode
            return f"https://dev.azure.com/{encoded_org}/{encoded_project}/_git/{encoded_repo}"
        
        return None
    
    def _sanitize_name(self, name: str) -> str:
        """Sanitize name for filesystem/repository"""
        import re
        name = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
        return name.lower()
    
    
    def _get_pat_token(self) -> Optional[str]:
        """Get Azure DevOps PAT token from environment"""
        return os.getenv('AZURE_DEVOPS_PAT') or os.getenv('SYSTEM_ACCESS_TOKEN')
    
    def _get_branch(self, subscription: Dict[str, Any]) -> str:
        """Get branch name for subscription with date and time"""
        from datetime import datetime
        
        base_branch = os.getenv('GIT_BRANCH') or self.git_config.get('branch', 'main')
        date_str = datetime.now().strftime('%Y-%m-%d-%H%M')
        branch_name = f"{base_branch}-{date_str}"
        
        return branch_name
    
    def _configure_git_credentials(self, repo_url: str) -> bool:
        """Configure git credentials for Azure DevOps"""
        pat_token = self._get_pat_token()
        if not pat_token:
            self.logger.error("Azure DevOps PAT token not found. Set AZURE_DEVOPS_PAT or SYSTEM_ACCESS_TOKEN")
            return False
        
        try:
            if 'dev.azure.com' in repo_url:
                org = self.azure_devops_config.get('organization')
                if org:
                    credential_url = f"https://{pat_token}@dev.azure.com/{org}"
                    git_config_cmd = [
                        'git', 'config', '--global',
                        f'url.{credential_url}/.insteadOf',
                        f'https://dev.azure.com/{org}/'
                    ]
                    result = subprocess.run(git_config_cmd, capture_output=True, text=True)
                    if result.returncode == 0:
                        self.logger.debug("Configured git credentials for Azure DevOps")
                    else:
                        self.logger.debug(f"Git credential config: {result.stderr}")
        except Exception as e:
            self.logger.warning(f"Could not configure git credentials: {str(e)}")
        
        return True
    
    def _init_git_repo(self, repo_path: Path) -> bool:
        """Initialize git repository if not already initialized"""
        git_dir = repo_path / '.git'
        if git_dir.exists():
            self.logger.debug("Git repository already initialized")
            return True
        
        try:
            subprocess.run(
                ['git', 'init'],
                cwd=str(repo_path),
                check=True,
                capture_output=True
            )
            self.logger.debug("Initialized git repository")
            return True
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to initialize git repository: {e.stderr.decode()}")
            return False
    
    def _create_gitignore(self, repo_path: Path):
        """Create .gitignore file for Terraform"""
        gitignore_path = repo_path / '.gitignore'
        gitignore_content = """# Terraform files
*.tfstate
*.tfstate.*
*.tfvars
.terraform/
.terraform.lock.hcl
crash.log
crash.*.log
*.tfplan
override.tf
override.tf.json
*_override.tf
*_override.tf.json

# IDE
.idea/
.vscode/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db
"""
        gitignore_path.write_text(gitignore_content)
        self.logger.debug("Created .gitignore file")
    
    def _create_readme(self, repo_path: Path, subscription: Dict[str, Any]):
        """Create README.md for the repository"""
        readme_path = repo_path / 'README.md'
        readme_content = f"""# Terraform Infrastructure as Code

This repository contains Terraform code for Azure resources exported from subscription: **{subscription.get('name', 'N/A')}**

## Subscription Information

- **Subscription ID**: `{subscription.get('id', 'N/A')}`
- **Subscription Name**: {subscription.get('name', 'N/A')}

## Structure

Each resource group is organized in its own directory:

```
resource-group-name/
├── main.tf
├── providers.tf
└── ...
```

## Usage

1. Navigate to a resource group directory:
   ```bash
   cd resource-group-name
   ```

2. Initialize Terraform:
   ```bash
   terraform init
   ```

3. Review the plan:
   ```bash
   terraform plan
   ```

## Notes

- This code was automatically generated using `aztfexport`
- Review and test before applying to production
- Update provider versions as needed
"""
        readme_path.write_text(readme_content)
        self.logger.debug("Created README.md file")
    
    def _add_remote(self, repo_path: Path, repo_url: str) -> bool:
        """Add or update git remote"""
        try:
            result = subprocess.run(
                ['git', 'remote', 'get-url', 'origin'],
                cwd=str(repo_path),
                capture_output=True
            )
            
            if result.returncode == 0:
                existing_url = result.stdout.decode().strip()
                if existing_url != repo_url:
                    subprocess.run(
                        ['git', 'remote', 'set-url', 'origin', repo_url],
                        cwd=str(repo_path),
                        check=True,
                        capture_output=True
                    )
                    self.logger.debug("Updated git remote URL")
            else:
                subprocess.run(
                    ['git', 'remote', 'add', 'origin', repo_url],
                    cwd=str(repo_path),
                    check=True,
                    capture_output=True
                )
                self.logger.debug("Added git remote")
            
            return True
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to configure git remote: {e.stderr.decode()}")
            return False
    
    def _checkout_branch(self, repo_path: Path, branch: str) -> bool:
        """Create and checkout branch locally"""
        try:
            result = subprocess.run(
                ['git', 'checkout', '-b', branch],
                cwd=str(repo_path),
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                self.logger.debug(f"Created and checked out branch: {branch}")
                return True
            elif 'already exists' in result.stderr.lower() or 'already on' in result.stderr.lower():
                result = subprocess.run(
                    ['git', 'checkout', branch],
                    cwd=str(repo_path),
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    self.logger.debug(f"Checked out existing branch: {branch}")
                    return True
            
            self.logger.warning(f"Could not checkout branch {branch}: {result.stderr}")
            return False
        except Exception as e:
            self.logger.warning(f"Error checking out branch: {str(e)}")
            return False
    
    def _commit_changes(self, repo_path: Path, subscription: Dict[str, Any]) -> bool:
        """Commit all changes to git"""
        try:
            subprocess.run(
                ['git', 'add', '-A'],
                cwd=str(repo_path),
                check=True,
                capture_output=True
            )
            
            commit_message = f"Export Terraform code for subscription: {subscription.get('name', subscription.get('id'))}"
            
            result = subprocess.run(
                ['git', 'commit', '-m', commit_message],
                cwd=str(repo_path),
                capture_output=True
            )
            
            if result.returncode == 0:
                self.logger.success(f"Committed changes: {commit_message}")
                return True
            elif 'nothing to commit' in result.stderr.decode().lower():
                self.logger.info("No changes to commit")
                return True
            else:
                self.logger.error(f"Failed to commit: {result.stderr.decode()}")
                return False
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to commit changes: {e.stderr.decode()}")
            return False
    
    def _push_to_remote(self, repo_path: Path, branch: str, repo_url: str) -> bool:
        """Push changes to remote repository"""
        pat_token = self._get_pat_token()
        if not pat_token:
            self.logger.error("PAT token not available for push")
            return False
        
        try:
            if 'dev.azure.com' in repo_url:
                parsed = urlparse(repo_url)
                path_parts = [p for p in parsed.path.split('/') if p]
                
                if len(path_parts) > 0:
                    auth_url = f'https://{pat_token}@dev.azure.com'
                    repo_url_with_auth = repo_url.replace('https://dev.azure.com', auth_url)
                else:
                    repo_url_with_auth = repo_url.replace('https://dev.azure.com', f'https://{pat_token}@dev.azure.com')
            else:
                repo_url_with_auth = repo_url
            
            subprocess.run(
                ['git', 'remote', 'set-url', 'origin', repo_url_with_auth],
                cwd=str(repo_path),
                check=True,
                capture_output=True,
                text=True
            )
            
            # Push with authentication
            result = subprocess.run(
                ['git', 'push', '-u', 'origin', branch, '--force'],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                env={**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': 'echo'}
            )
            
            if result.returncode == 0:
                self.logger.success(f"Pushed to {branch} branch")
                return True
            else:
                error_msg = result.stderr or result.stdout
                self.logger.error(f"Failed to push: {error_msg}")
                
                # Check if repository doesn't exist
                if 'not found' in error_msg.lower() or 'does not exist' in error_msg.lower():
                    self.logger.error("")
                    self.logger.error("Repository does not exist in Azure DevOps.")
                    self.logger.error("Please create the repository first:")
                    self.logger.error(f"  Organization: {self.azure_devops_config.get('organization', 'N/A')}")
                    self.logger.error(f"  Project: {self.azure_devops_config.get('project', 'N/A')}")
                    self.logger.error(f"  Repository: {repo_url.split('/_git/')[-1] if '/_git/' in repo_url else 'N/A'}")
                    self.logger.error("")
                    self.logger.error("You can create it via:")
                    self.logger.error("  - Azure DevOps Portal: Repos > New Repository")
                    self.logger.error("  - Azure CLI: az repos create --name <repo-name> --project <project>")
                
                return False
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to push to remote: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Error during git push: {str(e)}")
            return False
    
    def push_to_repo(
        self,
        subscription: Dict[str, Any],
        export_path: Path
    ) -> bool:
        """Push exported Terraform code to Azure DevOps repository"""
        repo_url = self._get_repo_url(subscription)
        if not repo_url:
            self.logger.warning(f"No repository URL configured for subscription {subscription.get('id')}")
            return False
        
        branch = self._get_branch(subscription)
        self.logger.info(f"Pushing to repository: {repo_url}")
        self.logger.info(f"Branch: {branch}")
        
        if not self._configure_git_credentials(repo_url):
            return False
        
        if not self._init_git_repo(export_path):
            return False
        
        self._create_gitignore(export_path)
        self._create_readme(export_path, subscription)
        
        if not self._add_remote(export_path, repo_url):
            return False
        
        if not self._checkout_branch(export_path, branch):
            self.logger.warning("Continuing with current branch")
        
        if not self._commit_changes(export_path, subscription):
            return False
        
        if not self._push_to_remote(export_path, branch, repo_url):
            return False
        
        self.logger.success(f"Successfully pushed to repository: {repo_url}")
        return True


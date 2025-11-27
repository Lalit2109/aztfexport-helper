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


class GitManager:
    """Manages git operations for Terraform repositories"""
    
    def __init__(self, base_dir: str = "./exports"):
        """Initialize git manager"""
        self.base_dir = Path(base_dir)
        self.git_username = os.getenv('GIT_USERNAME', 'azure-pipelines')
        self.git_email = os.getenv('GIT_EMAIL', 'azure-pipelines@devops.com')
        
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
    
    def _prepare_repo_url(self, repo_url: str, token: Optional[str] = None) -> str:
        """Prepare repository URL with authentication"""
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
    
    def initialize_repo(
        self,
        repo_path: Path,
        repo_url: Optional[str] = None,
        branch: str = 'main'
    ) -> bool:
        """Initialize or update a git repository"""
        try:
            repo_path = Path(repo_path)
            
            # Check if already a git repo
            if (repo_path / '.git').exists():
                print(f"  Repository already initialized: {repo_path}")
                repo = Repo(repo_path)
                
                # Check if remote exists
                if repo.remotes:
                    remote = repo.remotes.origin
                    if repo_url:
                        # Update remote URL if provided
                        token = self._get_azure_devops_token()
                        auth_url = self._prepare_repo_url(repo_url, token)
                        remote.set_url(auth_url)
                else:
                    # Add remote if it doesn't exist
                    if repo_url:
                        token = self._get_azure_devops_token()
                        auth_url = self._prepare_repo_url(repo_url, token)
                        repo.create_remote('origin', auth_url)
                
                return True
            
            # Initialize new repository
            print(f"  Initializing git repository: {repo_path}")
            repo = Repo.init(repo_path)
            
            # Configure git
            self._setup_git_config()
            
            # Add remote if URL provided
            if repo_url:
                token = self._get_azure_devops_token()
                auth_url = self._prepare_repo_url(repo_url, token)
                repo.create_remote('origin', auth_url)
            
            # Create initial commit if there are files
            if any(repo_path.iterdir()):
                repo.git.add(A=True)
                repo.index.commit('Initial commit: Terraform export')
            
            # Create and checkout branch
            if branch not in [ref.name for ref in repo.refs]:
                repo.git.checkout('-b', branch)
            
            return True
            
        except Exception as e:
            print(f"  ✗ Error initializing repository: {str(e)}")
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
            repo_path = Path(repo_path)
            
            if not (repo_path / '.git').exists():
                print(f"  ✗ Not a git repository: {repo_path}")
                return False
            
            repo = Repo(repo_path)
            
            # Check if there are changes
            if repo.is_dirty() or repo.untracked_files:
                # Stage all changes
                repo.git.add(A=True)
                
                # Commit
                repo.index.commit(commit_message)
                print(f"  ✓ Committed changes: {commit_message}")
            else:
                print(f"  No changes to commit")
                return True
            
            # Push to remote
            if repo.remotes:
                remote = repo.remotes.origin
                try:
                    if force:
                        repo.git.push('origin', branch, force=True)
                    else:
                        repo.git.push('origin', branch)
                    print(f"  ✓ Pushed to remote: {branch}")
                    return True
                except git.exc.GitCommandError as e:
                    print(f"  ✗ Error pushing to remote: {str(e)}")
                    # Try to pull and merge if branch exists remotely
                    try:
                        repo.git.pull('origin', branch, '--no-rebase')
                        repo.git.push('origin', branch)
                        print(f"  ✓ Pulled and pushed successfully")
                        return True
                    except:
                        print(f"  ✗ Could not resolve conflicts automatically")
                        return False
            else:
                print(f"  ⚠️  No remote configured, skipping push")
                return True
                
        except Exception as e:
            print(f"  ✗ Error in commit/push: {str(e)}")
            return False
    
    def push_subscription_repo(
        self,
        subscription: Dict[str, Any],
        subscription_dir: Path,
        branch: str = 'main'
    ) -> bool:
        """Push a subscription's repository to Azure DevOps"""
        subscription_name = subscription['name']
        repo_url = subscription.get('repo_url')
        
        print(f"\nPushing repository for: {subscription_name}")
        
        if not repo_url:
            print(f"  ⚠️  No repo_url configured, skipping push")
            return False
        
        # Initialize repo if needed
        if not self.initialize_repo(subscription_dir, repo_url, branch):
            return False
        
        # Commit and push
        commit_msg = f"Update: Terraform export for {subscription_name}"
        return self.commit_and_push(subscription_dir, commit_msg, branch)
    
    def push_all_repos(
        self,
        subscriptions: list,
        base_dir: Path,
        branch: str = 'main'
    ) -> Dict[str, bool]:
        """Push all subscription repositories"""
        results = {}
        
        for sub in subscriptions:
            if not sub.get('export_enabled', True):
                continue
            
            subscription_name = sub['name']
            subscription_dir = base_dir / self._sanitize_name(subscription_name)
            
            if not subscription_dir.exists():
                print(f"\n⚠️  Directory not found: {subscription_dir}")
                results[sub['id']] = False
                continue
            
            success = self.push_subscription_repo(sub, subscription_dir, branch)
            results[sub['id']] = success
        
        return results
    
    def _sanitize_name(self, name: str) -> str:
        """Sanitize name for filesystem"""
        import re
        name = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
        return name.lower()


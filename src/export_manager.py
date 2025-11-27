"""
Azure Resource Export Manager
Uses aztfexport to export resources organized by subscription and resource group
"""

import os
import subprocess
import yaml
import json
from pathlib import Path
from typing import Dict, Any, List, Optional


class ExportManager:
    """Manages Azure resource exports using aztfexport"""
    
    def __init__(self, config_path: str = "config/subscriptions.yaml"):
        """Initialize the export manager"""
        self.config = self._load_config(config_path)
        self.base_dir = self.config.get('output', {}).get('base_dir', './exports')
        
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    
    
    def _check_aztfexport_installed(self) -> bool:
        """Check if aztfexport is installed"""
        try:
            result = subprocess.run(
                ['aztfexport', '--version'],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def _install_aztfexport(self):
        """Install aztfexport if not present"""
        if self._check_aztfexport_installed():
            print("✓ aztfexport is already installed")
            return
        
        print("Installing aztfexport...")
        try:
            # Try to install via go install or download binary
            # aztfexport is typically installed via: go install github.com/Azure/aztfexport@latest
            # Or download from releases
            subprocess.run(
                ['go', 'install', 'github.com/Azure/aztfexport@latest'],
                check=True
            )
            print("✓ aztfexport installed successfully")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("⚠️  Could not install aztfexport automatically")
            print("Please install manually:")
            print("  Option 1: go install github.com/Azure/aztfexport@latest")
            print("  Option 2: Download from https://github.com/Azure/aztfexport/releases")
            raise
    
    def _get_resource_groups(self, subscription_id: str) -> List[str]:
        """Get list of resource groups in a subscription using Azure CLI"""
        resource_groups = []
        exclude_rgs = self.config.get('aztfexport', {}).get('exclude_resource_groups', [])
        
        try:
            result = subprocess.run(
                ['az', 'group', 'list', '--subscription', subscription_id, '--output', 'json'],
                capture_output=True,
                text=True,
                timeout=30,
                check=True
            )
            
            rgs_data = json.loads(result.stdout)
            for rg in rgs_data:
                rg_name = rg.get('name', '')
                if rg_name and rg_name not in exclude_rgs:
                    resource_groups.append(rg_name)
            
            print(f"  ✓ Found {len(resource_groups)} resource groups")
            return resource_groups
            
        except subprocess.TimeoutExpired:
            print(f"  ✗ Timeout listing resource groups (exceeded 30 seconds)")
            return []
        except FileNotFoundError:
            print(f"  ✗ Azure CLI not found. Please install: https://docs.microsoft.com/cli/azure/install-azure-cli")
            return []
        except subprocess.CalledProcessError as e:
            print(f"  ✗ Azure CLI command failed: {e.stderr}")
            print(f"  💡 Make sure you're logged in: az login")
            return []
        except json.JSONDecodeError as e:
            print(f"  ✗ Failed to parse Azure CLI output: {str(e)}")
            return []
        except Exception as e:
            print(f"  ✗ Error listing resource groups: {str(e)}")
            return []
    
    def _export_resource_group(
        self,
        subscription_id: str,
        subscription_name: str,
        resource_group: str,
        output_path: Path
    ) -> bool:
        """Export a single resource group using aztfexport"""
        print(f"    Exporting resource group: {resource_group}")
        
        # Ensure output directory exists
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Build aztfexport command
        cmd = [
            'aztfexport',
            'resource-group',
            resource_group,
            '--subscription-id', subscription_id,
            '--output-dir', str(output_path),
            '--non-interactive',
            '--append'
        ]
        
        # Add resource type filters if specified
        resource_types = self.config.get('aztfexport', {}).get('resource_types', [])
        if resource_types:
            for rt in resource_types:
                cmd.extend(['--resource-type', rt])
        
        # Add exclude resources if specified
        exclude_resources = self.config.get('aztfexport', {}).get('exclude_resources', [])
        if exclude_resources:
            for er in exclude_resources:
                cmd.extend(['--exclude', er])
        
        # Add additional flags
        additional_flags = self.config.get('aztfexport', {}).get('additional_flags', [])
        cmd.extend(additional_flags)
        
        try:
            # Use current environment - aztfexport will use Azure CLI credentials
            # from az login automatically
            env = os.environ.copy()
            # Ensure Azure CLI credentials are available to aztfexport
            # aztfexport uses Azure CLI SDK which will automatically use az login credentials
            
            result = subprocess.run(
                cmd,
                cwd=str(output_path.parent),
                capture_output=True,
                text=True,
                env=env,
                timeout=3600  # 1 hour timeout
            )
            
            if result.returncode == 0:
                print(f"    ✓ Successfully exported {resource_group}")
                return True
            else:
                print(f"    ✗ Error exporting {resource_group}:")
                print(f"      {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print(f"    ✗ Timeout exporting {resource_group}")
            return False
        except Exception as e:
            print(f"    ✗ Error exporting {resource_group}: {str(e)}")
            return False
    
    def export_subscription(
        self,
        subscription: Dict[str, Any],
        create_rg_folders: bool = True
    ) -> Dict[str, Any]:
        """Export all resource groups in a subscription"""
        subscription_id = subscription['id']
        subscription_name = subscription['name']
        
        print(f"\n{'='*60}")
        print(f"Exporting subscription: {subscription_name}")
        print(f"Subscription ID: {subscription_id}")
        print(f"{'='*60}")
        
        # Create subscription directory
        sub_dir = Path(self.base_dir) / self._sanitize_name(subscription_name)
        sub_dir.mkdir(parents=True, exist_ok=True)
        
        # Get resource groups
        print(f"\nDiscovering resource groups...")
        resource_groups = self._get_resource_groups(subscription_id)
        print(f"Found {len(resource_groups)} resource groups")
        
        results = {
            'subscription_id': subscription_id,
            'subscription_name': subscription_name,
            'resource_groups': {},
            'total_rgs': len(resource_groups),
            'successful_rgs': 0,
            'failed_rgs': 0
        }
        
        if not resource_groups:
            print("No resource groups to export")
            return results
        
        # Export each resource group
        for rg in resource_groups:
            if create_rg_folders:
                # Create resource group subfolder
                rg_dir = sub_dir / self._sanitize_name(rg)
            else:
                # Export directly to subscription folder
                rg_dir = sub_dir
            
            success = self._export_resource_group(
                subscription_id,
                subscription_name,
                rg,
                rg_dir
            )
            
            if success:
                results['resource_groups'][rg] = {
                    'path': str(rg_dir),
                    'status': 'success'
                }
                results['successful_rgs'] += 1
            else:
                results['resource_groups'][rg] = {
                    'path': str(rg_dir),
                    'status': 'failed'
                }
                results['failed_rgs'] += 1
        
        print(f"\n✓ Export completed for {subscription_name}")
        print(f"  Successful: {results['successful_rgs']}/{results['total_rgs']}")
        print(f"  Failed: {results['failed_rgs']}/{results['total_rgs']}")
        
        return results
    
    def export_all_subscriptions(self) -> Dict[str, Any]:
        """Export all enabled subscriptions"""
        # Check/install aztfexport
        try:
            self._install_aztfexport()
        except Exception as e:
            print(f"Error with aztfexport: {str(e)}")
            return {}
        
        # Ensure base directory exists
        Path(self.base_dir).mkdir(parents=True, exist_ok=True)
        
        subscriptions = self.config.get('subscriptions', [])
        create_rg_folders = self.config.get('output', {}).get('create_rg_folders', True)
        
        all_results = {}
        
        for sub in subscriptions:
            if not sub.get('export_enabled', True):
                print(f"\nSkipping subscription {sub['id']} (export disabled)")
                continue
            
            try:
                result = self.export_subscription(sub, create_rg_folders)
                all_results[sub['id']] = result
            except Exception as e:
                print(f"\n✗ Error exporting subscription {sub['id']}: {str(e)}")
                all_results[sub['id']] = {
                    'subscription_id': sub['id'],
                    'subscription_name': sub['name'],
                    'error': str(e)
                }
        
        return all_results
    
    def _sanitize_name(self, name: str) -> str:
        """Sanitize name for filesystem"""
        import re
        name = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
        return name.lower()


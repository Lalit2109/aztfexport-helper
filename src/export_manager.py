"""
Azure Resource Export Manager
Uses aztfexport to export resources organized by subscription and resource group
"""

import os
import platform
import subprocess
import shutil
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
        # Find Azure CLI path
        self.az_cli_path = self._find_az_cli()
    
    def _find_az_cli(self) -> str:
        """Find Azure CLI executable path (cross-platform)"""
        # First, try to find az in PATH (works on all platforms)
        az_path = shutil.which('az')
        if az_path:
            return az_path
        
        # Platform-specific common installation paths
        system = platform.system()
        
        if system == 'Windows':
            common_paths = [
                os.path.expanduser('~\\AppData\\Local\\Programs\\Azure CLI\\az.exe'),
                'C:\\Program Files\\Microsoft SDKs\\Azure\\CLI2\\wbin\\az.exe',
                'C:\\Program Files (x86)\\Microsoft SDKs\\Azure\\CLI2\\wbin\\az.exe',
            ]
        elif system == 'Darwin':  # macOS
            common_paths = [
                '/opt/homebrew/bin/az',  # Homebrew on Apple Silicon
                '/usr/local/bin/az',      # Homebrew on Intel Mac
                '/usr/bin/az',            # System installation
            ]
        else:  # Linux and other Unix-like
            common_paths = [
                '/usr/bin/az',
                '/usr/local/bin/az',
                '/opt/az/bin/az',
            ]
        
        for path in common_paths:
            if os.path.exists(path):
                return path
        
        # If not found, return 'az' and let subprocess handle it
        # This will work if az is in PATH when subprocess runs
        return 'az'
        
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
                [self.az_cli_path, 'group', 'list', '--subscription', subscription_id, '--output', 'json'],
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
            '--verbose'  # Add verbose mode to see what's happening
        ]
        
        # Note: Removed --append flag as it might cause issues
        # aztfexport will create files in the output directory
        
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
            print(f"    Running command: {' '.join(cmd)}")
            print(f"    Output directory: {output_path}")
            print(f"    This may take several minutes...")
            
            # Don't capture output - let it stream to console so user can see progress
            result = subprocess.run(
                cmd,
                cwd=str(output_path.parent),
                timeout=3600,  # 1 hour timeout
                # Remove capture_output to see real-time output
            )
            
            if result.returncode == 0:
                # Check if files were actually created
                tf_files = list(output_path.glob('*.tf'))
                if tf_files:
                    print(f"    ✓ Successfully exported {resource_group}")
                    print(f"      Created {len(tf_files)} Terraform file(s)")
                    return True
                else:
                    print(f"    ⚠️  Command succeeded but no .tf files found in {output_path}")
                    print(f"    💡 Check if the resource group has exportable resources")
                    return False
            else:
                print(f"    ✗ Error exporting {resource_group} (exit code: {result.returncode})")
                print(f"    💡 Check the output above for error details")
                return False
                
        except subprocess.TimeoutExpired:
            print(f"    ✗ Timeout exporting {resource_group} (exceeded 1 hour)")
            return False
        except FileNotFoundError:
            print(f"    ✗ aztfexport not found. Make sure it's installed and in PATH")
            print(f"    💡 Install with: go install github.com/Azure/aztfexport@latest")
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


"""
Azure Resource Export Manager
Uses aztfexport to export resources organized by subscription and resource group
"""

import os
import platform
import subprocess
import shutil
import fnmatch
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
    
    def _matches_exclude_pattern(self, rg_name: str, exclude_patterns: List[str]) -> bool:
        """Check if resource group name matches any exclude pattern (supports wildcards)"""
        for pattern in exclude_patterns:
            # Exact match
            if rg_name == pattern:
                return True
            # Wildcard match (supports * and ?)
            if fnmatch.fnmatch(rg_name, pattern):
                return True
        return False
        
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
        
        # Get global exclude patterns (with wildcard support)
        global_excludes = self.config.get('global_excludes', {}).get('resource_groups', [])
        # Get subscription-specific excludes
        local_excludes = self.config.get('aztfexport', {}).get('exclude_resource_groups', [])
        # Combine both lists
        exclude_patterns = global_excludes + local_excludes
        
        try:
            result = subprocess.run(
                [self.az_cli_path, 'group', 'list', '--subscription', subscription_id, '--output', 'json'],
                capture_output=True,
                text=True,
                timeout=30,
                check=True
            )
            
            rgs_data = json.loads(result.stdout)
            excluded_count = 0
            
            for rg in rgs_data:
                rg_name = rg.get('name', '').strip()  # Strip whitespace
                if rg_name:
                    # Check if it matches any exclude pattern (with wildcard support)
                    if self._matches_exclude_pattern(rg_name, exclude_patterns):
                        excluded_count += 1
                        continue
                    
                    # Ensure it's a single resource group name (not a list or multiple values)
                    if isinstance(rg_name, str) and rg_name:
                        resource_groups.append(rg_name)
                    else:
                        print(f"  ⚠️  Skipping invalid resource group name: {rg_name}")
            
            if excluded_count > 0:
                print(f"  ✓ Found {len(resource_groups)} resource groups (excluded {excluded_count} matching patterns)")
            else:
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
    
    def _build_resource_graph_query(
        self,
        exclude_resource_types: List[str],
        custom_query: Optional[str] = None
    ) -> str:
        """
        Build Azure Resource Graph query to exclude specific resource types
        If custom_query is provided, use it directly. Otherwise, build from exclude_resource_types.
        """
        if custom_query:
            return custom_query
        
        if not exclude_resource_types:
            return ""
        
        # Build Azure Resource Graph query predicate
        # Format: "type != 'ResourceType1' and type != 'ResourceType2' ..."
        # Note: aztfexport query expects just the predicate part (without 'where' keyword)
        conditions = []
        for resource_type in exclude_resource_types:
            # Escape single quotes in resource type
            escaped_type = resource_type.replace("'", "''")
            conditions.append(f"type != '{escaped_type}'")
        
        # Combine with 'and' - this means: exclude all these types
        # The query will be: type != 'Type1' and type != 'Type2' ...
        query = " and ".join(conditions)
        
        return query
    
    def _export_resource_group(
        self,
        subscription_id: str,
        subscription_name: str,
        resource_group: str,
        output_path: Path
    ) -> bool:
        """Export a single resource group using aztfexport"""
        print(f"    Exporting resource group: {resource_group}")
        
        # Convert to absolute path to avoid path resolution issues
        output_path = output_path.resolve()
        
        # Ensure parent directory exists (aztfexport will create the final directory)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Build aztfexport command
        # Ensure resource group name is a single string (handle spaces/special chars)
        rg_name = str(resource_group).strip()
        
        # Check if we should use query mode (for excluding resource types)
        exclude_resource_types = self.config.get('aztfexport', {}).get('exclude_resource_types', [])
        custom_query = self.config.get('aztfexport', {}).get('query', None)
        use_query_mode = bool(exclude_resource_types) or bool(custom_query)
        
        if use_query_mode:
            # Use query mode with Azure Resource Graph query
            query = self._build_resource_graph_query(exclude_resource_types, custom_query)
            if query:
                print(f"    Using query mode to exclude resource types")
                if exclude_resource_types:
                    print(f"    Excluding types: {', '.join(exclude_resource_types)}")
                print(f"    Query: {query}")
                
                # aztfexport query mode syntax: aztfexport query [flags] <ARG where predicate>
                # The query predicate MUST be the last argument (not resource group name)
                # Note: -n is --non-interactive, NOT for query name! Use --non-interactive instead
                cmd = [
                    'aztfexport',
                    'query',
                    '--subscription-id', subscription_id,
                    '--output-dir', str(output_path),
                    '--non-interactive'  # Use full flag name, NOT -n (which is the same flag)
                ]
                
                # Add resource group filter to query predicate
                # The query should filter by resourceGroup in the predicate itself
                # Query format: "type != 'Type' and resourceGroup == 'rg-name'"
                # Note: aztfexport query expects just the predicate, not "where ..."
                if rg_name:
                    # Add resource group filter to the query predicate
                    if query:
                        # Combine type exclusions with resource group filter
                        query_with_rg = f"{query} and resourceGroup == '{rg_name}'"
                    else:
                        query_with_rg = f"resourceGroup == '{rg_name}'"
                else:
                    query_with_rg = query
                
                # Add additional flags if specified
                additional_flags = self.config.get('aztfexport', {}).get('additional_flags', [])
                cmd.extend(additional_flags)
                
                # Query predicate MUST be last argument (per aztfexport documentation)
                # This is the ARG where predicate, not the resource group name
                cmd.append(query_with_rg)
            else:
                # Fall back to resource-group mode if query is empty
                use_query_mode = False
        
        if not use_query_mode:
            # Use standard resource-group mode
            # According to aztfexport documentation, resource group name MUST be LAST
            # Command structure: aztfexport resource-group [flags] <resource-group-name>
            cmd = [
                'aztfexport',
                'resource-group',
                '--subscription-id', subscription_id,
                '--output-dir', str(output_path),
                '--non-interactive'
            ]
            
            # Add resource type filters if specified
            resource_types = self.config.get('aztfexport', {}).get('resource_types', [])
            if resource_types:
                for rt in resource_types:
                    cmd.extend(['--resource-type', rt])
            
            # Add exclude resources if specified (for specific resource IDs)
            exclude_resources = self.config.get('aztfexport', {}).get('exclude_resources', [])
            if exclude_resources:
                for er in exclude_resources:
                    cmd.extend(['--exclude', er])
            
            # Add additional flags
            additional_flags = self.config.get('aztfexport', {}).get('additional_flags', [])
            cmd.extend(additional_flags)
            
            # Resource group name MUST be last (per aztfexport documentation)
            cmd.append(rg_name)
        
        try:
            # Print command with proper quoting for resource group name
            cmd_display = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in cmd)
            print(f"    Running command: {cmd_display}")
            print(f"    Resource group: {rg_name}")
            print(f"    Output directory: {output_path}")
            print(f"    This may take several minutes...")
            
            # Don't capture output - let it stream to console so user can see progress
            # Use the base directory as cwd to avoid path issues
            result = subprocess.run(
                cmd,
                cwd=str(Path(self.base_dir).resolve()),
                timeout=3600,  # 1 hour timeout
                # Remove capture_output to see real-time output
            )
            
            if result.returncode == 0:
                # Check if files were actually created
                # aztfexport might create files directly in output_path or in a subdirectory
                # Check both the specified directory and recursively
                tf_files_direct = list(output_path.glob('*.tf'))
                tf_files_recursive = list(output_path.rglob('*.tf'))
                
                # Use recursive search to find all .tf files
                tf_files = tf_files_recursive if tf_files_recursive else tf_files_direct
                
                if tf_files:
                    # Get the actual directory where files were created
                    actual_dir = tf_files[0].parent
                    print(f"    ✓ Successfully exported {resource_group}")
                    print(f"      Created {len(tf_files)} Terraform file(s)")
                    if actual_dir != output_path:
                        print(f"      Files created in: {actual_dir}")
                    return True
                else:
                    # Show what's actually in the directory for debugging
                    if output_path.exists():
                        all_files = list(output_path.iterdir())
                        print(f"    ⚠️  Command succeeded but no .tf files found")
                        print(f"    Checking directory: {output_path}")
                        print(f"    Directory exists: {output_path.exists()}")
                        if all_files:
                            print(f"    Found {len(all_files)} item(s) in directory:")
                            for item in all_files[:5]:  # Show first 5 items
                                item_type = "directory" if item.is_dir() else "file"
                                print(f"      - {item.name} ({item_type})")
                            if len(all_files) > 5:
                                print(f"      ... and {len(all_files) - 5} more")
                        else:
                            print(f"    Directory is empty")
                    else:
                        print(f"    ⚠️  Command succeeded but output directory does not exist: {output_path}")
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
        
        # Create subscription directory under base_dir
        # Structure: {base_dir}/{subscription-name}/
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


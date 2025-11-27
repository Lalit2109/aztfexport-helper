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
    
    def _is_nested_resource_type(self, resource_type: str) -> tuple[bool, str, str]:
        """
        Check if resource type is nested (child resource) and extract parent/child types
        Returns: (is_nested, parent_type, child_name)
        Example: "Microsoft.OperationalInsights/workspaces/savedSearches" 
                 -> (True, "Microsoft.OperationalInsights/workspaces", "savedSearches")
        """
        parts = resource_type.split('/')
        if len(parts) == 3:  # Provider/ResourceType/ChildType
            return True, f"{parts[0]}/{parts[1]}", parts[2]
        return False, "", ""
    
    def _get_nested_resources(
        self,
        subscription_id: str,
        resource_group: str,
        parent_type: str,
        child_name: str
    ) -> List[str]:
        """Get all nested (child) resources of a specific type"""
        resource_ids = []
        
        try:
            # First, get all parent resources
            parent_result = subprocess.run(
                [
                    self.az_cli_path,
                    'resource', 'list',
                    '--subscription', subscription_id,
                    '--resource-group', resource_group,
                    '--resource-type', parent_type,
                    '--output', 'json'
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=True
            )
            
            parents = json.loads(parent_result.stdout)
            total_children = 0
            
            for parent in parents:
                parent_id = parent.get('id', '')
                parent_name = parent.get('name', '')
                
                if not parent_id or not parent_name:
                    continue
                
                # Try different methods to query child resources
                child_resources = []
                
                # Method 1: Try using Azure CLI resource list with full child type
                try:
                    child_type = f"{parent_type}/{child_name}"
                    child_result = subprocess.run(
                        [
                            self.az_cli_path,
                            'resource', 'list',
                            '--subscription', subscription_id,
                            '--resource-group', resource_group,
                            '--resource-type', child_type,
                            '--output', 'json'
                        ],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=True
                    )
                    child_resources = json.loads(child_result.stdout)
                except:
                    pass
                
                # Method 2: Try specific Azure CLI commands for known nested resources
                if not child_resources:
                    if child_name.lower() == 'savedsearches' and 'operationalinsights' in parent_type.lower():
                        try:
                            child_result = subprocess.run(
                                [
                                    self.az_cli_path,
                                    'monitor', 'log-analytics', 'workspace', 'saved-search', 'list',
                                    '--workspace-name', parent_name,
                                    '--resource-group', resource_group,
                                    '--output', 'json'
                                ],
                                capture_output=True,
                                text=True,
                                timeout=30,
                                check=True
                            )
                            child_resources = json.loads(child_result.stdout)
                        except:
                            pass
                    # Add more specific handlers for other nested resource types here
                    # elif child_name.lower() == 'diagnosticsettings':
                    #     ...
                
                # Method 3: Construct child resource IDs if we know the pattern
                # Some child resources might not be queryable, so we construct IDs
                if not child_resources:
                    # For some nested resources, we might need to query them differently
                    # or they might be discovered during export
                    print(f"      ⚠️  Could not query {child_name} for {parent_type} {parent_name}")
                    # We'll rely on pattern-based exclusion or aztfexport discovery
                
                # Extract child resource IDs
                for child in child_resources:
                    child_id = child.get('id', '')
                    if not child_id and parent_id:
                        # Construct child ID if not provided
                        child_resource_name = child.get('name', '')
                        if child_resource_name:
                            child_id = f"{parent_id}/{child_name}/{child_resource_name}"
                    
                    if child_id and child_id not in resource_ids:
                        resource_ids.append(child_id)
                        total_children += 1
            
            if total_children > 0:
                print(f"      Found {total_children} {child_name} resource(s) across {len(parents)} {parent_type.split('/')[-1]}(s)")
            elif parents:
                print(f"      Found {len(parents)} {parent_type.split('/')[-1]}(s) but could not query {child_name} - may need manual exclusion")
            
        except Exception as e:
            print(f"      ⚠️  Error querying nested resources {parent_type}/{child_name}: {str(e)}")
        
        return resource_ids
    
    def _get_resources_by_type(
        self,
        subscription_id: str,
        resource_group: str,
        resource_types: List[str]
    ) -> List[str]:
        """Get all resource IDs of specified types in a resource group"""
        resource_ids = []
        
        for resource_type in resource_types:
            try:
                # Check if this is a nested resource type
                is_nested, parent_type, child_name = self._is_nested_resource_type(resource_type)
                
                if is_nested:
                    # Handle nested resources
                    print(f"      Querying nested resource type: {resource_type}")
                    nested_ids = self._get_nested_resources(
                        subscription_id,
                        resource_group,
                        parent_type,
                        child_name
                    )
                    resource_ids.extend(nested_ids)
                else:
                    # Try to query resources of this type directly
                    result = subprocess.run(
                        [
                            self.az_cli_path,
                            'resource', 'list',
                            '--subscription', subscription_id,
                            '--resource-group', resource_group,
                            '--resource-type', resource_type,
                            '--output', 'json'
                        ],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=True
                    )
                    
                    resources = json.loads(result.stdout)
                    for resource in resources:
                        resource_id = resource.get('id', '')
                        if resource_id:
                            resource_ids.append(resource_id)
                    
                    if resources:
                        print(f"      Found {len(resources)} resource(s) of type {resource_type} to exclude")
                    
            except subprocess.TimeoutExpired:
                print(f"      ⚠️  Timeout querying resources of type {resource_type}")
            except subprocess.CalledProcessError as e:
                # If resource type query fails, check if it's a nested resource
                is_nested, parent_type, child_name = self._is_nested_resource_type(resource_type)
                if is_nested:
                    print(f"      Trying alternative method for nested resource {resource_type}")
                    nested_ids = self._get_nested_resources(
                        subscription_id,
                        resource_group,
                        parent_type,
                        child_name
                    )
                    resource_ids.extend(nested_ids)
                else:
                    print(f"      ⚠️  Error querying resources of type {resource_type}: {e.stderr}")
            except json.JSONDecodeError:
                print(f"      ⚠️  Failed to parse resource list for type {resource_type}")
            except Exception as e:
                print(f"      ⚠️  Unexpected error querying {resource_type}: {str(e)}")
        
        return resource_ids
    
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
        
        # According to aztfexport documentation, resource group name MUST be LAST
        # Command structure: aztfexport resource-group [flags] <resource-group-name>
        # Use absolute path to avoid path resolution issues
        cmd = [
            'aztfexport',
            'resource-group',
            '--subscription-id', subscription_id,
            '--output-dir', str(output_path),
            '--non-interactive'
            # Note: --verbose is not a valid flag for aztfexport
        ]
        
        # Add resource type filters if specified
        resource_types = self.config.get('aztfexport', {}).get('resource_types', [])
        if resource_types:
            for rt in resource_types:
                cmd.extend(['--resource-type', rt])
        
        # Get exclude resources list
        exclude_resources = list(self.config.get('aztfexport', {}).get('exclude_resources', []))
        
        # If exclude_resource_types is specified, get all resources of those types and add to exclude list
        exclude_resource_types = self.config.get('aztfexport', {}).get('exclude_resource_types', [])
        if exclude_resource_types:
            print(f"    Excluding resource types: {', '.join(exclude_resource_types)}")
            excluded_resource_ids = self._get_resources_by_type(
                subscription_id,
                resource_group,
                exclude_resource_types
            )
            exclude_resources.extend(excluded_resource_ids)
            if excluded_resource_ids:
                print(f"    Total resources to exclude: {len(excluded_resource_ids)}")
        
        # Handle pattern-based exclusions (for child resources like saved searches)
        # If resource type contains savedSearches, also add pattern-based exclusion
        for resource_type in exclude_resource_types:
            if 'savedSearches' in resource_type.lower() or '/savedSearches' in resource_type:
                # Add pattern to exclude all saved searches using additional flags
                # aztfexport supports --exclude with patterns
                print(f"    Adding pattern-based exclusion for saved searches")
                # We'll add this as an additional flag or use resource ID pattern
        
        # Add exclude resources if specified
        if exclude_resources:
            for er in exclude_resources:
                cmd.extend(['--exclude', er])
        
        # For saved searches, if we couldn't find them via API, use a workaround:
        # Query all workspaces and construct saved search IDs, or use additional flags
        # Check if we have saved searches in exclude types but didn't find any IDs
        has_saved_searches_type = any('savedSearches' in rt.lower() for rt in exclude_resource_types)
        if has_saved_searches_type and not any('savedSearches' in rid.lower() for rid in exclude_resources):
            print(f"    ⚠️  Could not find saved searches via API, using alternative exclusion method")
            # Try to get workspace IDs and construct saved search patterns
            # We'll add them to additional_flags or use a post-processing approach
        
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


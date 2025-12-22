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
from logger import get_logger


class ExportManager:
    """Manages Azure resource exports using aztfexport"""
    
    def __init__(self, config_path: str = "config/subscriptions.yaml"):
        """Initialize the export manager"""
        self.logger = get_logger()
        self.config = self._load_config(config_path)
        
        # Set log level from config if specified
        log_level = self.config.get('logging', {}).get('level', os.getenv('LOG_LEVEL', 'INFO'))
        from logger import set_log_level
        set_log_level(log_level)
        self.logger = get_logger()
        
        self.base_dir = os.getenv('OUTPUT_DIR') or self.config.get('output', {}).get('base_dir', './exports')
        self.az_cli_path = self._find_az_cli()
    
    def _find_az_cli(self) -> str:
        """Find Azure CLI executable path (cross-platform)"""
        az_path = shutil.which('az')
        if az_path:
            return az_path
        
        system = platform.system()
        if system == 'Windows':
            common_paths = [
                os.path.expanduser('~\\AppData\\Local\\Programs\\Azure CLI\\az.exe'),
                'C:\\Program Files\\Microsoft SDKs\\Azure\\CLI2\\wbin\\az.exe',
                'C:\\Program Files (x86)\\Microsoft SDKs\\Azure\\CLI2\\wbin\\az.exe',
            ]
        elif system == 'Darwin':
            common_paths = [
                '/opt/homebrew/bin/az',
                '/usr/local/bin/az',
                '/usr/bin/az',
            ]
        else:
            common_paths = [
                '/usr/bin/az',
                '/usr/local/bin/az',
                '/opt/az/bin/az',
            ]
        
        for path in common_paths:
            if os.path.exists(path):
                return path
        
        return 'az'
    
    def _matches_exclude_pattern(self, rg_name: str, exclude_patterns: List[str]) -> bool:
        """Check if resource group name matches any exclude pattern (supports wildcards, case-insensitive)"""
        rg_name_lower = rg_name.lower()
        for pattern in exclude_patterns:
            pattern_lower = pattern.lower()
            # Case-insensitive exact match
            if rg_name_lower == pattern_lower:
                return True
            # Case-insensitive wildcard match using fnmatchcase with lowercased strings
            if fnmatch.fnmatchcase(rg_name_lower, pattern_lower):
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
            self.logger.success("aztfexport is already installed")
            return
        
        self.logger.info("Installing aztfexport...")
        try:
            subprocess.run(
                ['go', 'install', 'github.com/Azure/aztfexport@latest'],
                check=True
            )
            self.logger.success("aztfexport installed successfully")
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.logger.error("Could not install aztfexport automatically")
            self.logger.info("Please install manually:")
            self.logger.info("  Option 1: go install github.com/Azure/aztfexport@latest")
            self.logger.info("  Option 2: Download from https://github.com/Azure/aztfexport/releases")
            raise
    
    def get_subscriptions_from_azure(self) -> List[Dict[str, Any]]:
        """Get all subscriptions accessible to the current Azure CLI account"""
        subscriptions = []
        
        try:
            result = subprocess.run(
                [self.az_cli_path, 'account', 'list', '--query', '[].{id:id, name:name, state:state}', '--output', 'json'],
                capture_output=True,
                text=True,
                timeout=30,
                check=True
            )
            
            subs_data = json.loads(result.stdout)
            
            for sub in subs_data:
                sub_id = sub.get('id', '').strip()
                sub_name = sub.get('name', '').strip()
                sub_state = sub.get('state', '').strip()
                
                # Only include enabled subscriptions
                if sub_id and sub_state.lower() == 'enabled':
                    subscriptions.append({
                        'id': sub_id,
                        'name': sub_name or sub_id  # Use ID as name if name is missing
                    })
                elif sub_id:
                    self.logger.debug(f"Skipping subscription {sub_id} (state: {sub_state})")
            
            self.logger.success(f"Found {len(subscriptions)} enabled subscription(s) accessible to this account")
            return subscriptions
            
        except subprocess.TimeoutExpired:
            self.logger.error("Timeout listing subscriptions (exceeded 30 seconds)")
            return []
        except FileNotFoundError:
            self.logger.error("Azure CLI not found. Please install: https://docs.microsoft.com/cli/azure/install-azure-cli")
            return []
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Azure CLI command failed: {e.stderr}")
            self.logger.info("Make sure you're logged in: az login")
            return []
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse Azure CLI output: {str(e)}")
            return []
        except Exception as e:
            self.logger.error(f"Error listing subscriptions: {str(e)}")
            return []
    
    def _get_resource_groups(self, subscription_id: str, subscription_name: str = None) -> List[str]:
        """Get list of resource groups in a subscription using Azure CLI"""
        resource_groups = []
        global_excludes = self.config.get('global_excludes', {}).get('resource_groups', [])
        local_excludes = self.config.get('aztfexport', {}).get('exclude_resource_groups', [])
        exclude_patterns = global_excludes + local_excludes
        
        sub_display = f" ({subscription_name})" if subscription_name else ""
        
        try:
            result = subprocess.run(
                [self.az_cli_path, 'group', 'list', '--subscription', subscription_id, '--output', 'json'],
                capture_output=True,
                text=True,
                timeout=30,
                check=True
            )
            
            rgs_data = json.loads(result.stdout)
            excluded_rgs = []  # List of (rg_name, matching_pattern) tuples
            
            for rg in rgs_data:
                rg_name = rg.get('name', '').strip()
                if rg_name:
                    # Check which pattern matches (if any) - case-insensitive
                    matching_pattern = None
                    rg_name_lower = rg_name.lower()
                    for pattern in exclude_patterns:
                        pattern_lower = pattern.lower()
                        # Case-insensitive exact match
                        if rg_name_lower == pattern_lower:
                            matching_pattern = pattern
                            break
                        # Case-insensitive wildcard match
                        if fnmatch.fnmatchcase(rg_name_lower, pattern_lower):
                            matching_pattern = pattern
                            break
                    
                    if matching_pattern:
                        excluded_rgs.append((rg_name, matching_pattern))
                        continue
                    
                    if isinstance(rg_name, str) and rg_name:
                        resource_groups.append(rg_name)
                    else:
                        self.logger.warning(f"Skipping invalid resource group name: {rg_name}")
            
            # Log detailed exclusion information
            if excluded_rgs:
                self.logger.info(f"Excluded resource groups{sub_display}:")
                for rg_name, pattern in excluded_rgs:
                    self.logger.info(f"  ✗ {rg_name} (matched pattern: {pattern})")
            
            # Log resource groups that will be processed
            if resource_groups:
                self.logger.info(f"Resource groups to process{sub_display}:")
                for rg_name in resource_groups:
                    self.logger.info(f"  ✓ {rg_name}")
            
            # Summary log
            total_rgs = len(resource_groups) + len(excluded_rgs)
            if excluded_rgs:
                self.logger.success(f"Found {total_rgs} total resource groups{sub_display}: {len(resource_groups)} to process, {len(excluded_rgs)} excluded")
            else:
                self.logger.success(f"Found {len(resource_groups)} resource groups{sub_display} (none excluded)")
            
            return resource_groups
            
        except subprocess.TimeoutExpired:
            self.logger.error("Timeout listing resource groups (exceeded 30 seconds)")
            return []
        except FileNotFoundError:
            self.logger.error("Azure CLI not found. Please install: https://docs.microsoft.com/cli/azure/install-azure-cli")
            return []
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Azure CLI command failed: {e.stderr}")
            self.logger.info("Make sure you're logged in: az login")
            return []
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse Azure CLI output: {str(e)}")
            return []
        except Exception as e:
            self.logger.error(f"Error listing resource groups: {str(e)}")
            return []
    
    def _build_resource_graph_query(
        self,
        exclude_resource_types: List[str],
        custom_query: Optional[str] = None
    ) -> str:
        """Build Azure Resource Graph query to exclude resource types"""
        if custom_query:
            return custom_query
        
        if not exclude_resource_types:
            return ""
        
        conditions = []
        for resource_type in exclude_resource_types:
            escaped_type = resource_type.replace("'", "''")
            conditions.append(f"type != '{escaped_type}'")
        
        return " and ".join(conditions)
    
    def _parse_aztfexport_output(self, output: str) -> Dict[str, Any]:
        """Parse aztfexport output to extract resource statistics"""
        import re
        stats = {
            'total_resources': 0,
            'exported_resources': 0,
            'failed_resources': 0,
            'skipped_resources': 0,
            'error_type': None,
            'error_details': []
        }
        
        output_lower = output.lower()
        
        # Try to find resource counts in output
        # Common patterns: "exported X resources", "X resources exported", "failed: X", etc.
        patterns = [
            (r'exported\s+(\d+)\s+resources?', 'exported_resources'),
            (r'(\d+)\s+resources?\s+exported', 'exported_resources'),
            (r'successfully\s+exported\s+(\d+)', 'exported_resources'),
            (r'failed\s+to\s+export\s+(\d+)', 'failed_resources'),
            (r'(\d+)\s+resources?\s+failed', 'failed_resources'),
            (r'skipped\s+(\d+)\s+resources?', 'skipped_resources'),
            (r'(\d+)\s+resources?\s+skipped', 'skipped_resources'),
            (r'total\s+(\d+)\s+resources?', 'total_resources'),
            (r'(\d+)\s+total\s+resources?', 'total_resources'),
        ]
        
        for pattern, key in patterns:
            matches = re.findall(pattern, output_lower)
            if matches:
                try:
                    value = int(matches[-1])  # Take the last match
                    if stats[key] == 0:  # Only set if not already found
                        stats[key] = value
                except (ValueError, IndexError):
                    pass
        
        # If we found exported but no total, estimate total
        if stats['total_resources'] == 0 and stats['exported_resources'] > 0:
            stats['total_resources'] = stats['exported_resources'] + stats['failed_resources'] + stats['skipped_resources']
        
        # Categorize errors
        permission_keywords = ['permission', 'unauthorized', 'access denied', 'forbidden', 'authorization', 'role', 'rbac']
        if any(keyword in output_lower for keyword in permission_keywords):
            stats['error_type'] = 'permission'
        elif 'error' in output_lower or 'failed' in output_lower:
            stats['error_type'] = 'other'
        
        # Extract error details (last few error lines)
        error_lines = [line for line in output.split('\n') if any(kw in line.lower() for kw in ['error', 'failed', 'denied', 'unauthorized'])]
        if error_lines:
            stats['error_details'] = error_lines[-5:]  # Last 5 error lines
        
        return stats
    
    def _export_resource_group(
        self,
        subscription_id: str,
        subscription_name: str,
        resource_group: str,
        output_path: Path
    ) -> Dict[str, Any]:
        """Export a single resource group using aztfexport
        
        Returns:
            Dictionary with export status and resource statistics:
            {
                'success': bool,
                'total_resources': int,
                'exported_resources': int,
                'failed_resources': int,
                'skipped_resources': int,
                'error_type': str or None,
                'error_details': list
            }
        """
        self.logger.info(f"Exporting resource group: {resource_group}")
        
        # Initialize result
        result = {
            'success': False,
            'total_resources': 0,
            'exported_resources': 0,
            'failed_resources': 0,
            'skipped_resources': 0,
            'error_type': None,
            'error_details': []
        }
        
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rg_name = str(resource_group).strip()
        
        exclude_resource_types = self.config.get('aztfexport', {}).get('exclude_resource_types', [])
        custom_query = self.config.get('aztfexport', {}).get('query', None)
        use_query_mode = bool(exclude_resource_types) or bool(custom_query)
        
        if use_query_mode:
            query = self._build_resource_graph_query(exclude_resource_types, custom_query)
            if query:
                self.logger.info("Using query mode to exclude resource types")
                if exclude_resource_types:
                    self.logger.debug(f"Excluding types: {', '.join(exclude_resource_types)}")
                self.logger.debug(f"Query: {query}")
                
                cmd = [
                    'aztfexport',
                    'query',
                    '--subscription-id', subscription_id,
                    '--output-dir', str(output_path),
                    '--non-interactive',
                    '--plain-ui'
                ]
                
                if rg_name:
                    query_with_rg = f"{query} and resourceGroup == '{rg_name}'" if query else f"resourceGroup == '{rg_name}'"
                else:
                    query_with_rg = query
                
                additional_flags = self.config.get('aztfexport', {}).get('additional_flags', [])
                cmd.extend(additional_flags)
                cmd.append(query_with_rg)
            else:
                use_query_mode = False
        
        if not use_query_mode:
            cmd = [
                'aztfexport',
                'resource-group',
                '--subscription-id', subscription_id,
                '--output-dir', str(output_path),
                '--non-interactive',
                '--plain-ui'
            ]
            
            resource_types = self.config.get('aztfexport', {}).get('resource_types', [])
            if resource_types:
                for rt in resource_types:
                    cmd.extend(['--resource-type', rt])
            
            exclude_resources = self.config.get('aztfexport', {}).get('exclude_resources', [])
            if exclude_resources:
                for er in exclude_resources:
                    cmd.extend(['--exclude', er])
            
            additional_flags = self.config.get('aztfexport', {}).get('additional_flags', [])
            cmd.extend(additional_flags)
            cmd.append(rg_name)
        
        try:
            cmd_display = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in cmd)
            self.logger.debug(f"Running command: {cmd_display}")
            self.logger.debug(f"Resource group: {rg_name}")
            self.logger.debug(f"Output directory: {output_path}")
            self.logger.info("This may take several minutes...")
            
            env = os.environ.copy()
            env['AZTFEXPORT_NON_INTERACTIVE'] = 'true'
            env['TERM'] = 'dumb'  # Set terminal type to dumb
            env['NO_COLOR'] = '1'  # Disable color output
            
            # Use script to emulate TTY (prevents aztfexport TTY errors)
            import shutil
            script_cmd = shutil.which('script')
            
            if script_cmd:
                cmd_str = ' '.join(f'"{arg}"' if ' ' in arg or '"' in arg else arg for arg in cmd)
                script_wrapper = [script_cmd, '-q', '-e', '-c', cmd_str]
                final_cmd = script_wrapper
            else:
                final_cmd = cmd
            
            self.logger.info(f"Starting export for {resource_group}...")
            process = subprocess.Popen(
                final_cmd,
                cwd=str(Path(self.base_dir).resolve()),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            output_lines = []
            seen_lines = set()
            
            try:
                import sys
                for line in iter(process.stdout.readline, ''):
                    if line:
                        line = line.rstrip()
                        if line not in seen_lines:
                            seen_lines.add(line)
                            output_lines.append(line)
                            sys.stdout.write(line + '\n')
                            sys.stdout.flush()
            finally:
                process.stdout.close()
                exit_code = process.wait(timeout=3600)
            
            full_output = '\n'.join(output_lines)
            
            # Parse output for resource statistics
            parsed_stats = self._parse_aztfexport_output(full_output)
            result.update(parsed_stats)
            
            self.logger.info("")
            if exit_code == 0:
                self.logger.info("=" * 60)
                self.logger.success(f"✓ EXPORT COMPLETED SUCCESSFULLY for {resource_group}")
                if result['exported_resources'] > 0:
                    self.logger.info(f"   Resources exported: {result['exported_resources']}")
                if result['failed_resources'] > 0:
                    self.logger.warning(f"   Resources failed: {result['failed_resources']}")
                if result['skipped_resources'] > 0:
                    self.logger.info(f"   Resources skipped: {result['skipped_resources']}")
                self.logger.info("=" * 60)
            else:
                self.logger.info("=" * 60)
                self.logger.error(f"✗ EXPORT FAILED for {resource_group} (exit code: {exit_code})")
                if result['error_type']:
                    self.logger.error(f"   Error type: {result['error_type']}")
                self.logger.info("=" * 60)
            
            if exit_code == 0:
                tf_files_direct = list(output_path.glob('*.tf'))
                tf_files_recursive = list(output_path.rglob('*.tf'))
                tf_files = tf_files_recursive if tf_files_recursive else tf_files_direct
                
                if tf_files:
                    actual_dir = tf_files[0].parent
                    self.logger.success(f"✓✓ Successfully exported {resource_group}")
                    self.logger.info(f"   Created {len(tf_files)} Terraform file(s)")
                    if actual_dir != output_path:
                        self.logger.debug(f"   Files created in: {actual_dir}")
                    result['success'] = True
                    # If we couldn't parse resource count, estimate from tf files
                    if result['exported_resources'] == 0:
                        # Rough estimate: count .tf files (each may contain multiple resources)
                        result['exported_resources'] = len(tf_files)
                        result['total_resources'] = len(tf_files)
                    return result
                else:
                    if output_path.exists():
                        all_files = list(output_path.iterdir())
                        self.logger.warning(f"⚠ Export completed but no .tf files found for {resource_group}")
                        self.logger.debug(f"   Checking directory: {output_path}")
                        if all_files:
                            self.logger.debug(f"   Found {len(all_files)} item(s) in directory:")
                            for item in all_files[:5]:
                                item_type = "directory" if item.is_dir() else "file"
                                self.logger.debug(f"     - {item.name} ({item_type})")
                            if len(all_files) > 5:
                                self.logger.debug(f"     ... and {len(all_files) - 5} more")
                        else:
                            self.logger.debug("   Directory is empty")
                    else:
                        self.logger.warning(f"⚠ Export completed but output directory does not exist: {output_path}")
                    self.logger.info("   Check if the resource group has exportable resources")
                    result['success'] = False
                    return result
            else:
                self.logger.error(f"✗✗ Error exporting {resource_group} (exit code: {exit_code})")
                if full_output:
                    error_lines = full_output.strip().split('\n')
                    # Show last 20 lines of error output
                    self.logger.error("   Error output (last 20 lines):")
                    for line in error_lines[-20:]:
                        if line.strip():
                            self.logger.error(f"     {line}")
                self.logger.info("   Check the output above for error details")
                result['success'] = False
                return result
                
        except subprocess.TimeoutExpired:
            if 'process' in locals():
                try:
                    process.kill()
                except:
                    pass
            self.logger.error(f"✗✗ Timeout exporting {resource_group} (exceeded 1 hour)")
            result['success'] = False
            result['error_type'] = 'timeout'
            result['error_details'] = ['Export timeout: exceeded 1 hour']
            return result
        except FileNotFoundError:
            self.logger.error("aztfexport not found. Make sure it's installed and in PATH")
            self.logger.info("Install with: go install github.com/Azure/aztfexport@latest")
            result['success'] = False
            result['error_type'] = 'tool_not_found'
            result['error_details'] = ['aztfexport not found in PATH']
            return result
        except Exception as e:
            self.logger.error(f"Error exporting {resource_group}: {str(e)}")
            result['success'] = False
            result['error_type'] = 'exception'
            result['error_details'] = [str(e)]
            return result
    
    def export_subscription(
        self,
        subscription: Dict[str, Any],
        create_rg_folders: bool = True
    ) -> Dict[str, Any]:
        """Export all resource groups in a subscription"""
        subscription_id = subscription['id']
        subscription_name = subscription['name']
        
        self.logger.info("=" * 60)
        self.logger.info(f"Exporting subscription: {subscription_name}")
        self.logger.info(f"Subscription ID: {subscription_id}")
        self.logger.info("=" * 60)
        
        sub_dir = Path(self.base_dir) / self._sanitize_name(subscription_name)
        sub_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger.info("Discovering resource groups...")
        resource_groups = self._get_resource_groups(subscription_id, subscription_name)
        
        results = {
            'subscription_id': subscription_id,
            'subscription_name': subscription_name,
            'resource_groups': {},
            'total_rgs': len(resource_groups),
            'successful_rgs': 0,
            'failed_rgs': 0,
            # Resource-level statistics
            'total_resources': 0,
            'exported_resources': 0,
            'failed_resources': 0,
            'skipped_resources': 0
        }
        
        if not resource_groups:
            self.logger.info("No resource groups to export")
            return results
        
        for rg in resource_groups:
            if create_rg_folders:
                rg_dir = sub_dir / self._sanitize_name(rg)
            else:
                rg_dir = sub_dir
            
            rg_result = self._export_resource_group(
                subscription_id,
                subscription_name,
                rg,
                rg_dir
            )
            
            # Handle both old boolean return (backward compatibility) and new dict return
            if isinstance(rg_result, dict):
                success = rg_result.get('success', False)
                # Aggregate resource statistics
                results['total_resources'] += rg_result.get('total_resources', 0)
                results['exported_resources'] += rg_result.get('exported_resources', 0)
                results['failed_resources'] += rg_result.get('failed_resources', 0)
                results['skipped_resources'] += rg_result.get('skipped_resources', 0)
                
                results['resource_groups'][rg] = {
                    'path': str(rg_dir),
                    'status': 'success' if success else 'failed',
                    'total_resources': rg_result.get('total_resources', 0),
                    'exported_resources': rg_result.get('exported_resources', 0),
                    'failed_resources': rg_result.get('failed_resources', 0),
                    'skipped_resources': rg_result.get('skipped_resources', 0),
                    'error_type': rg_result.get('error_type'),
                    'error_details': rg_result.get('error_details', [])
                }
            else:
                # Backward compatibility: boolean return
                success = bool(rg_result)
                results['resource_groups'][rg] = {
                    'path': str(rg_dir),
                    'status': 'success' if success else 'failed'
                }
            
            if success:
                results['successful_rgs'] += 1
            else:
                results['failed_rgs'] += 1
        
        self.logger.success(f"Export completed for {subscription_name}")
        self.logger.info(f"Resource Groups - Successful: {results['successful_rgs']}/{results['total_rgs']}, Failed: {results['failed_rgs']}/{results['total_rgs']}")
        if results['total_resources'] > 0:
            self.logger.info(f"Resources - Total: {results['total_resources']}, Exported: {results['exported_resources']}, Failed: {results['failed_resources']}, Skipped: {results['skipped_resources']}")
        
        return results
    
    def export_all_subscriptions(self) -> Dict[str, Any]:
        """Export all enabled subscriptions
        
        By default, all subscriptions accessible via Azure CLI are exported unless:
        - subscription ID is in exclude_subscriptions list
        """
        try:
            self._install_aztfexport()
        except Exception as e:
            self.logger.error(f"Error with aztfexport: {str(e)}")
            return {}
        
        Path(self.base_dir).mkdir(parents=True, exist_ok=True)
        
        subscriptions = self.get_subscriptions_from_azure()
        if not subscriptions:
            self.logger.error("No subscriptions found. Check Azure CLI authentication and permissions.")
            return {}
        
        exclude_subscriptions_raw = self.config.get('exclude_subscriptions', {})
        # Flatten prod and non-prod lists into single list
        if isinstance(exclude_subscriptions_raw, dict):
            prod_list = exclude_subscriptions_raw.get('prod') or []
            non_prod_list = exclude_subscriptions_raw.get('non-prod') or []
            exclude_subscriptions = (prod_list if isinstance(prod_list, list) else []) + (non_prod_list if isinstance(non_prod_list, list) else [])
        else:
            # Backward compatibility: if it's a list, use it directly
            exclude_subscriptions = exclude_subscriptions_raw if isinstance(exclude_subscriptions_raw, list) else []
        create_rg_folders = self.config.get('output', {}).get('create_rg_folders', True)
        all_results = {}
        
        for sub in subscriptions:
            subscription_id = sub.get('id')
            subscription_name = sub.get('name', subscription_id)
            
            # Check exclusion by ID or name
            is_excluded = subscription_id in exclude_subscriptions or subscription_name in exclude_subscriptions
            if is_excluded:
                self.logger.info(f"Skipping subscription {subscription_name} ({subscription_id}) (in exclude_subscriptions list)")
                continue
            
            try:
                result = self.export_subscription(sub, create_rg_folders)
                all_results[subscription_id] = result
            except Exception as e:
                self.logger.error(f"Error exporting subscription {subscription_id}: {str(e)}")
                all_results[subscription_id] = {
                    'subscription_id': subscription_id,
                    'subscription_name': sub.get('name', subscription_id),
                    'error': str(e)
                }
        
        return all_results
    
    def _sanitize_name(self, name: str) -> str:
        """Sanitize name for filesystem"""
        import re
        name = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
        return name.lower()
    
    def push_subscription_to_git(
        self,
        subscription: Dict[str, Any],
        export_path: Path
    ) -> bool:
        """Push exported subscription to git repository"""
        from git_manager import GitManager
        
        git_manager = GitManager(self.config)
        return git_manager.push_to_repo(subscription, export_path)
    
    def cleanup_export_directory(self, subscription: Dict[str, Any]) -> bool:
        """Clean up export directory after successful git push"""
        subscription_name = subscription.get('name')
        if not subscription_name:
            return False
        
        try:
            sub_dir = Path(self.base_dir) / self._sanitize_name(subscription_name)
            if sub_dir.exists():
                import shutil
                shutil.rmtree(sub_dir)
                self.logger.info(f"Cleaned up export directory: {sub_dir}")
                return True
        except Exception as e:
            self.logger.warning(f"Failed to cleanup export directory: {str(e)}")
            return False
    
    def check_disk_space(self, min_free_percent: float = 5.0) -> bool:
        """Check if there's enough free disk space"""
        try:
            import shutil
            stat = shutil.disk_usage(self.base_dir)
            free_percent = (stat.free / stat.total) * 100
            
            if free_percent < min_free_percent:
                self.logger.warning(f"⚠️  Low disk space: {free_percent:.1f}% free (minimum: {min_free_percent}%)")
                self.logger.warning(f"   Total: {stat.total / (1024**3):.2f} GB, Free: {stat.free / (1024**3):.2f} GB")
                return False
            else:
                self.logger.debug(f"Disk space check: {free_percent:.1f}% free")
                return True
        except Exception as e:
            self.logger.warning(f"Could not check disk space: {str(e)}")
            return True  # Continue if check fails


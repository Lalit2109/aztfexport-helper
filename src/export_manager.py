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
        """Check if resource group name matches any exclude pattern (supports wildcards)"""
        for pattern in exclude_patterns:
            if rg_name == pattern or fnmatch.fnmatch(rg_name, pattern):
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
    
    def _get_resource_groups(self, subscription_id: str) -> List[str]:
        """Get list of resource groups in a subscription using Azure CLI"""
        resource_groups = []
        global_excludes = self.config.get('global_excludes', {}).get('resource_groups', [])
        local_excludes = self.config.get('aztfexport', {}).get('exclude_resource_groups', [])
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
                rg_name = rg.get('name', '').strip()
                if rg_name:
                    if self._matches_exclude_pattern(rg_name, exclude_patterns):
                        excluded_count += 1
                        continue
                    
                    if isinstance(rg_name, str) and rg_name:
                        resource_groups.append(rg_name)
                    else:
                        self.logger.warning(f"Skipping invalid resource group name: {rg_name}")
            
            if excluded_count > 0:
                self.logger.success(f"Found {len(resource_groups)} resource groups (excluded {excluded_count} matching patterns)")
            else:
                self.logger.success(f"Found {len(resource_groups)} resource groups")
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
    
    def _export_resource_group(
        self,
        subscription_id: str,
        subscription_name: str,
        resource_group: str,
        output_path: Path
    ) -> bool:
        """Export a single resource group using aztfexport"""
        self.logger.info(f"Exporting resource group: {resource_group}")
        
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
            self.logger.info("")
            if exit_code == 0:
                self.logger.info("=" * 60)
                self.logger.success(f"✓ EXPORT COMPLETED SUCCESSFULLY for {resource_group}")
                self.logger.info("=" * 60)
            else:
                self.logger.info("=" * 60)
                self.logger.error(f"✗ EXPORT FAILED for {resource_group} (exit code: {exit_code})")
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
                    return True
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
                    return False
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
                return False
                
        except subprocess.TimeoutExpired:
            if 'process' in locals():
                try:
                    process.kill()
                except:
                    pass
            self.logger.error(f"✗✗ Timeout exporting {resource_group} (exceeded 1 hour)")
            return False
        except FileNotFoundError:
            self.logger.error("aztfexport not found. Make sure it's installed and in PATH")
            self.logger.info("Install with: go install github.com/Azure/aztfexport@latest")
            return False
        except Exception as e:
            self.logger.error(f"Error exporting {resource_group}: {str(e)}")
            return False
    
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
        resource_groups = self._get_resource_groups(subscription_id)
        self.logger.info(f"Found {len(resource_groups)} resource groups")
        
        results = {
            'subscription_id': subscription_id,
            'subscription_name': subscription_name,
            'resource_groups': {},
            'total_rgs': len(resource_groups),
            'successful_rgs': 0,
            'failed_rgs': 0
        }
        
        if not resource_groups:
            self.logger.info("No resource groups to export")
            return results
        
        for rg in resource_groups:
            if create_rg_folders:
                rg_dir = sub_dir / self._sanitize_name(rg)
            else:
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
        
        self.logger.success(f"Export completed for {subscription_name}")
        self.logger.info(f"Successful: {results['successful_rgs']}/{results['total_rgs']}")
        self.logger.info(f"Failed: {results['failed_rgs']}/{results['total_rgs']}")
        
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


"""
Azure Resource Export Service
Uses aztfexport to export resources at subscription level
"""

import os
import subprocess
import shutil
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional
from .logger import get_logger
from .config import load_config
from .azure_client import AzureClient


class ExportService:
    """Manages Azure resource exports using aztfexport at subscription level"""
    
    def __init__(
        self,
        subscription_id: str,
        subscription_name: str,
        config_path: str = "config/subscriptions.yaml",
        output_dir: Optional[str] = None
    ):
        """Initialize the export service
        
        Args:
            subscription_id: Azure subscription ID
            subscription_name: Subscription display name
            config_path: Path to configuration YAML file
            output_dir: Output directory for exports (defaults to config or ./exports)
        """
        self.logger = get_logger()
        self.subscription_id = subscription_id
        self.subscription_name = subscription_name
        self.config = load_config(config_path)
        
        log_level = self.config.get('logging', {}).get('level', os.getenv('LOG_LEVEL', 'INFO'))
        from .logger import set_log_level
        set_log_level(log_level)
        self.logger = get_logger()
        
        self.base_dir = output_dir or os.getenv('OUTPUT_DIR') or self.config.get('output', {}).get('base_dir', './exports')
        self.az_cli_path = 'az'
        self.azure_client = AzureClient(self.az_cli_path)
    
    def get_resource_groups(self) -> List[str]:
        """Get list of resource groups in subscription (for reporting/logging)
        
        Returns:
            List of resource group names to process
        """
        global_excludes = self.config.get('global_excludes', {}).get('resource_groups', [])
        local_excludes = self.config.get('aztfexport', {}).get('exclude_resource_groups', [])
        exclude_patterns = global_excludes + local_excludes
        
        return self.azure_client.get_resource_groups(
            self.subscription_id,
            self.subscription_name,
            exclude_patterns
        )
    
    def _build_resource_graph_query(
        self,
        exclude_resource_types: List[str],
        exclude_resource_groups: List[str],
        custom_query: Optional[str] = None
    ) -> str:
        """Build Azure Resource Graph query to exclude resource types and resource groups"""
        if custom_query:
            return custom_query
        
        conditions = []
        
        if exclude_resource_types:
            for resource_type in exclude_resource_types:
                escaped_type = resource_type.replace("'", "''")
                conditions.append(f"type != '{escaped_type}'")
        
        if exclude_resource_groups:
            for rg in exclude_resource_groups:
                escaped_rg = rg.replace("'", "''")
                conditions.append(f"resourceGroup != '{escaped_rg}'")
        
        return " and ".join(conditions) if conditions else ""
    
    def _sanitize_name(self, name: str) -> str:
        """Sanitize name for filesystem"""
        import re
        name = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
        return name.lower()
    
    def export_subscription(self) -> Dict[str, Any]:
        """Export entire subscription using aztfexport
        
        Returns:
            Dictionary with export results
        """
        self.logger.info("=" * 60)
        self.logger.info(f"Exporting subscription: {self.subscription_name}")
        self.logger.info(f"Subscription ID: {self.subscription_id}")
        self.logger.info("=" * 60)
        
        sub_dir = Path(self.base_dir) / self._sanitize_name(self.subscription_name)
        sub_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger.info("Discovering resource groups...")
        resource_groups = self.get_resource_groups()
        
        results = {
            'subscription_id': self.subscription_id,
            'subscription_name': self.subscription_name,
            'total_rgs': len(resource_groups),
            'successful_rgs': 0,
            'failed_rgs': 0,
            'error': None
        }
        
        if not resource_groups:
            self.logger.info("No resource groups to export")
            return results
        
        exclude_resource_types = self.config.get('aztfexport', {}).get('exclude_resource_types', [])
        exclude_resource_groups_config = self.config.get('aztfexport', {}).get('exclude_resource_groups', [])
        global_excludes = self.config.get('global_excludes', {}).get('resource_groups', [])
        all_exclude_rgs = list(set(exclude_resource_groups_config + global_excludes))
        custom_query = self.config.get('aztfexport', {}).get('query', None)
        
        use_query_mode = bool(exclude_resource_types) or bool(all_exclude_rgs) or bool(custom_query)
        
        if all_exclude_rgs and not use_query_mode:
            use_query_mode = True
        
        output_path = sub_dir.resolve()
        output_path.mkdir(parents=True, exist_ok=True)
        
        try:
            if use_query_mode:
                query = self._build_resource_graph_query(exclude_resource_types, all_exclude_rgs, custom_query)
                if query:
                    self.logger.info("Using query mode to filter resources")
                    if exclude_resource_types:
                        self.logger.debug(f"Excluding resource types: {', '.join(exclude_resource_types)}")
                    if all_exclude_rgs:
                        self.logger.debug(f"Excluding resource groups: {', '.join(all_exclude_rgs)}")
                    self.logger.debug(f"Query: {query}")
                    
                    cmd = [
                        'aztfexport',
                        'query',
                        '--subscription-id', self.subscription_id,
                        '--output-dir', str(output_path),
                        '--non-interactive',
                        '--plain-ui'
                    ]
                    
                    additional_flags = self.config.get('aztfexport', {}).get('additional_flags', [])
                    cmd.extend(additional_flags)
                    cmd.append(query)
                else:
                    use_query_mode = False
            
            if not use_query_mode:
                cmd = [
                    'aztfexport',
                    'subscription',
                    '--subscription-id', self.subscription_id,
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
            
            cmd_display = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in cmd)
            self.logger.debug(f"Running command: {cmd_display}")
            self.logger.debug(f"Output directory: {output_path}")
            self.logger.info("This may take several minutes...")
            
            env = os.environ.copy()
            env['AZTFEXPORT_NON_INTERACTIVE'] = 'true'
            env['TERM'] = 'dumb'
            env['NO_COLOR'] = '1'
            
            script_cmd = shutil.which('script')
            
            if script_cmd:
                cmd_str = ' '.join(f'"{arg}"' if ' ' in arg or '"' in arg else arg for arg in cmd)
                script_wrapper = [script_cmd, '-q', '-e', '-c', cmd_str]
                final_cmd = script_wrapper
            else:
                final_cmd = cmd
            
            self.logger.info(f"Starting export for subscription {self.subscription_name}...")
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
            failed_resources = []
            
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
                            
                            if 'error' in line.lower() or 'failed' in line.lower():
                                failed_resources.append(line)
            finally:
                process.stdout.close()
                exit_code = process.wait(timeout=3600)
            
            full_output = '\n'.join(output_lines)
            self.logger.info("")
            
            if exit_code == 0:
                self.logger.info("=" * 60)
                self.logger.success(f"✓ EXPORT COMPLETED SUCCESSFULLY for {self.subscription_name}")
                self.logger.info("=" * 60)
                
                tf_files_direct = list(output_path.glob('*.tf'))
                tf_files_recursive = list(output_path.rglob('*.tf'))
                tf_files = tf_files_recursive if tf_files_recursive else tf_files_direct
                
                if tf_files:
                    self.logger.success(f"✓✓ Successfully exported {self.subscription_name}")
                    self.logger.info(f"   Created {len(tf_files)} Terraform file(s)")
                    results['successful_rgs'] = len(resource_groups)
                    results['failed_rgs'] = 0
                else:
                    self.logger.warning(f"⚠ Export completed but no .tf files found for {self.subscription_name}")
                    results['successful_rgs'] = 0
                    results['failed_rgs'] = len(resource_groups)
            else:
                self.logger.info("=" * 60)
                self.logger.error(f"✗ EXPORT FAILED for {self.subscription_name} (exit code: {exit_code})")
                self.logger.info("=" * 60)
                
                if full_output:
                    error_lines = full_output.strip().split('\n')
                    self.logger.error("   Error output (last 20 lines):")
                    for line in error_lines[-20:]:
                        if line.strip():
                            self.logger.error(f"     {line}")
                
                results['successful_rgs'] = 0
                results['failed_rgs'] = len(resource_groups)
                results['error'] = f"Export failed with exit code {exit_code}"
                if failed_resources:
                    results['failed_resources'] = failed_resources[:10]
            
            self.logger.success(f"Export completed for {self.subscription_name}")
            self.logger.info(f"Successful: {results['successful_rgs']}/{results['total_rgs']}")
            self.logger.info(f"Failed: {results['failed_rgs']}/{results['total_rgs']}")
            
            return results
                
        except subprocess.TimeoutExpired:
            if 'process' in locals():
                try:
                    process.kill()
                except:
                    pass
            self.logger.error(f"✗✗ Timeout exporting {self.subscription_name} (exceeded 1 hour)")
            results['error'] = "Export timeout exceeded 1 hour"
            results['failed_rgs'] = len(resource_groups)
            return results
        except FileNotFoundError:
            self.logger.error("aztfexport not found. Make sure it's installed and in PATH")
            self.logger.info("Install with: go install github.com/Azure/aztfexport@latest")
            results['error'] = "aztfexport not found"
            results['failed_rgs'] = len(resource_groups)
            return results
        except Exception as e:
            self.logger.error(f"Error exporting {self.subscription_name}: {str(e)}")
            import traceback
            traceback.print_exc()
            results['error'] = str(e)
            results['failed_rgs'] = len(resource_groups)
            return results
    
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
            return True


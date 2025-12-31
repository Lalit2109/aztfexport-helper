"""
Azure Resource Export Service
Uses aztfexport to export resources per resource group or at subscription level
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
    """Manages Azure resource exports using aztfexport"""
    
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
        """Get list of resource groups in subscription (excluded ones are filtered out)
        
        Returns:
            List of resource group names to process (excluded ones already removed)
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
    
    def _sanitize_name(self, name: str) -> str:
        """Sanitize name for filesystem"""
        import re
        name = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
        return name.lower()
    
    def _export_resource_group(
        self,
        resource_group: str,
        output_path: Path
    ) -> bool:
        """Export a single resource group using aztfexport
        
        Args:
            resource_group: Resource group name to export
            output_path: Output directory for this resource group
            
        Returns:
            True if export succeeded, False otherwise
        """
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
                self.logger.debug("Using query mode to exclude resource types")
                if exclude_resource_types:
                    self.logger.debug(f"Excluding types: {', '.join(exclude_resource_types)}")
                self.logger.debug(f"Query: {query}")
                
                query_with_rg = f"{query} and resourceGroup == '{rg_name}'" if query else f"resourceGroup == '{rg_name}'"
                
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
                cmd.append(query_with_rg)
            else:
                use_query_mode = False
        
        if not use_query_mode:
            cmd = [
                'aztfexport',
                'resource-group',
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
            cmd.append(rg_name)
        
        try:
            cmd_display = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in cmd)
            self.logger.debug(f"Running command: {cmd_display}")
            self.logger.debug(f"Resource group: {rg_name}")
            self.logger.debug(f"Output directory: {output_path}")
            
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
            
            if exit_code == 0:
                tf_files = list(output_path.glob('*.tf')) + list(output_path.rglob('*.tf'))
                if tf_files:
                    self.logger.success(f"✓ Successfully exported {rg_name}")
                    return True
                else:
                    self.logger.warning(f"⚠ Export completed but no .tf files found for {rg_name}")
                    return False
            else:
                self.logger.error(f"✗ Export failed for {rg_name} (exit code: {exit_code})")
                return False
                
        except subprocess.TimeoutExpired:
            if 'process' in locals():
                try:
                    process.kill()
                except:
                    pass
            self.logger.error(f"✗✗ Timeout exporting {rg_name} (exceeded 1 hour)")
            return False
        except FileNotFoundError:
            self.logger.error("aztfexport not found. Make sure it's installed and in PATH")
            self.logger.info("Install with: go install github.com/Azure/aztfexport@latest")
            return False
        except Exception as e:
            self.logger.error(f"Error exporting {rg_name}: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    def export_subscription(self, create_rg_folders: Optional[bool] = None) -> Dict[str, Any]:
        """Export subscription by exporting each resource group individually
        
        Args:
            create_rg_folders: If True, create separate folder per resource group.
                             If False, export all RGs to subscription folder.
                             If None, use config value (default: True)
        
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
        
        if create_rg_folders is None:
            create_rg_folders = self.config.get('output', {}).get('create_rg_folders', True)
        
        results = {
            'subscription_id': self.subscription_id,
            'subscription_name': self.subscription_name,
            'resource_groups': {},
            'total_rgs': len(resource_groups),
            'successful_rgs': 0,
            'failed_rgs': 0,
            'error': None
        }
        
        if not resource_groups:
            self.logger.info("No resource groups to export")
            return results
        
        self.logger.info(f"Exporting {len(resource_groups)} resource group(s)...")
        if create_rg_folders:
            self.logger.info("Creating separate folder per resource group")
        else:
            self.logger.info("Exporting all resource groups to subscription folder")
        
        for rg in resource_groups:
            if create_rg_folders:
                rg_dir = sub_dir / self._sanitize_name(rg)
            else:
                rg_dir = sub_dir
            
            success = self._export_resource_group(rg, rg_dir)
            
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
        
        self.logger.info("")
        self.logger.success(f"Export completed for {self.subscription_name}")
        self.logger.info(f"Successful: {results['successful_rgs']}/{results['total_rgs']}")
        self.logger.info(f"Failed: {results['failed_rgs']}/{results['total_rgs']}")
        
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

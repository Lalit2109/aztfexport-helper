"""
Azure CLI wrapper for resource group discovery
"""

import subprocess
import json
import fnmatch
from typing import List, Dict, Any
from .logger import get_logger


class AzureClient:
    """Azure CLI wrapper for resource operations"""
    
    def __init__(self, az_cli_path: str = 'az'):
        """Initialize Azure Client
        
        Args:
            az_cli_path: Path to Azure CLI executable (default: 'az')
        """
        self.logger = get_logger()
        self.az_cli_path = az_cli_path
    
    def get_resource_groups(
        self,
        subscription_id: str,
        subscription_name: str = None,
        exclude_patterns: List[str] = None
    ) -> List[str]:
        """Get list of resource groups in a subscription using Azure CLI
        
        Args:
            subscription_id: Azure subscription ID
            subscription_name: Subscription display name (for logging)
            exclude_patterns: List of patterns to exclude (supports wildcards)
        
        Returns:
            List of resource group names to process
        """
        resource_groups = []
        exclude_patterns = exclude_patterns or []
        
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
            excluded_rgs = []
            
            for rg in rgs_data:
                rg_name = rg.get('name', '').strip()
                if rg_name:
                    matching_pattern = None
                    rg_name_lower = rg_name.lower()
                    for pattern in exclude_patterns:
                        pattern_lower = pattern.lower()
                        if rg_name_lower == pattern_lower:
                            matching_pattern = pattern
                            break
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
            
            if excluded_rgs:
                self.logger.info(f"Excluded resource groups{sub_display}:")
                for rg_name, pattern in excluded_rgs:
                    self.logger.info(f"  ✗ {rg_name} (matched pattern: {pattern})")
            
            if resource_groups:
                self.logger.info(f"Resource groups to process{sub_display}:")
                for rg_name in resource_groups:
                    self.logger.info(f"  ✓ {rg_name}")
            
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


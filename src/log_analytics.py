"""
Log Analytics module for sending backup status and timing data to Azure Log Analytics
Uses the Data Collector API with HMAC-SHA256 authentication
"""

import os
import json
import hmac
import hashlib
import base64
from datetime import datetime
from typing import Dict, Any, Optional, List
from requests import post, RequestException
from logger import get_logger


class LogAnalyticsSender:
    """Send data to Azure Log Analytics workspace using Data Collector API"""
    
    def __init__(self, workspace_id: Optional[str] = None, shared_key: Optional[str] = None):
        """Initialize Log Analytics sender
        
        Args:
            workspace_id: Log Analytics workspace ID (or from LOG_ANALYTICS_WORKSPACE_ID env var)
            shared_key: Log Analytics shared key (or from LOG_ANALYTICS_SHARED_KEY env var)
        """
        self.logger = get_logger()
        self.workspace_id = workspace_id or os.getenv('LOG_ANALYTICS_WORKSPACE_ID')
        self.shared_key = shared_key or os.getenv('LOG_ANALYTICS_SHARED_KEY')
        
        if not self.workspace_id or not self.shared_key:
            self.logger.warning("Log Analytics credentials not configured. Skipping Log Analytics integration.")
            self.enabled = False
        else:
            self.enabled = True
            self.api_version = "2016-04-01"
            self.uri = f"https://{self.workspace_id}.ods.opinsights.azure.com/api/logs?api-version={self.api_version}"
    
    def _build_signature(self, date: str, content_length: int, method: str = "POST", content_type: str = "application/json") -> str:
        """Build HMAC-SHA256 signature for Log Analytics API authentication"""
        x_headers = f"x-ms-date:{date}"
        string_to_sign = f"{method}\n{content_length}\n{content_type}\n{x_headers}\n/api/logs"
        bytes_to_sign = string_to_sign.encode('utf-8')
        decoded_key = base64.b64decode(self.shared_key)
        signature = base64.b64encode(
            hmac.new(decoded_key, bytes_to_sign, digestmod=hashlib.sha256).digest()
        ).decode('utf-8')
        return f"SharedKey {self.workspace_id}:{signature}"
    
    def send_data(self, data: List[Dict[str, Any]], log_type: str = "Infra_terraform_backup") -> bool:
        """Send data to Log Analytics workspace
        
        Args:
            data: List of dictionaries containing data to send
            log_type: Log type name (table name in Log Analytics)
        
        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            self.logger.debug("Log Analytics not enabled, skipping send")
            return False
        
        if not data or len(data) == 0:
            self.logger.warning("No data provided to send to Log Analytics")
            return False
        
        try:
            # Convert data to JSON
            json_body = json.dumps(data)
            content_length = len(json_body.encode('utf-8'))
            
            # Build signature
            date = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')
            signature = self._build_signature(date, content_length)
            
            # Build headers
            headers = {
                "Authorization": signature,
                "Log-Type": log_type,
                "x-ms-date": date,
                "Content-Type": "application/json",
                "time-generated-field": "TimeGenerated"
            }
            
            # Send request
            response = post(self.uri, data=json_body, headers=headers, timeout=30)
            response.raise_for_status()
            
            self.logger.success(f"Successfully sent {len(data)} record(s) to Log Analytics workspace")
            return True
            
        except RequestException as e:
            self.logger.error(f"Failed to send data to Log Analytics: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.text
                    self.logger.debug(f"Error response: {error_detail}")
                except:
                    pass
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error sending data to Log Analytics: {str(e)}")
            return False
    
    def send_subscription_backup_status(
        self,
        subscription_id: str,
        subscription_name: str,
        status: str,
        start_time: datetime,
        end_time: datetime,
        total_resource_groups: int,
        successful_resource_groups: int,
        failed_resource_groups: int,
        git_push_status: str = "skipped",
        error_message: Optional[str] = None,
        total_resources: int = 0,
        exported_resources: int = 0,
        failed_resources: int = 0,
        skipped_resources: int = 0
    ) -> bool:
        """Send subscription backup status to Log Analytics
        
        Args:
            subscription_id: Azure subscription ID
            subscription_name: Subscription display name
            status: Status (success/failed)
            start_time: Export start time
            end_time: Export end time
            total_resource_groups: Total number of resource groups
            successful_resource_groups: Number of successfully exported resource groups
            failed_resource_groups: Number of failed resource groups
            git_push_status: Git push status (success/failed/skipped)
            error_message: Error message if any
            total_resources: Total number of resources (optional)
            exported_resources: Number of successfully exported resources (optional)
            failed_resources: Number of failed resources (optional)
            skipped_resources: Number of skipped resources (optional)
        
        Returns:
            True if successful, False otherwise
        """
        duration_seconds = (end_time - start_time).total_seconds()
        
        record = {
            "TimeGenerated": start_time.isoformat() + "Z",
            "SubscriptionId": subscription_id,
            "SubscriptionName": subscription_name,
            "Status": status,
            "StartTime": start_time.isoformat() + "Z",
            "EndTime": end_time.isoformat() + "Z",
            "DurationSeconds": duration_seconds,
            "TotalResourceGroups": total_resource_groups,
            "SuccessfulResourceGroups": successful_resource_groups,
            "FailedResourceGroups": failed_resource_groups,
            "GitPushStatus": git_push_status
        }
        
        # Add resource-level statistics if provided
        if total_resources > 0 or exported_resources > 0 or failed_resources > 0 or skipped_resources > 0:
            record["TotalResources"] = total_resources
            record["ExportedResources"] = exported_resources
            record["FailedResources"] = failed_resources
            record["SkippedResources"] = skipped_resources
        
        if error_message:
            record["ErrorMessage"] = error_message
        
        return self.send_data([record])


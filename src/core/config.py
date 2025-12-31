"""
Configuration management module
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any


def load_config(config_path: str = "config/subscriptions.yaml") -> Dict[str, Any]:
    """Load configuration from YAML file
    
    Args:
        config_path: Path to configuration YAML file
    
    Returns:
        Dictionary containing configuration
    """
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
    with open(config_file, 'r') as f:
        return yaml.safe_load(f) or {}


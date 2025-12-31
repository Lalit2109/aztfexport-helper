#!/usr/bin/env python3
"""
Find which SPN to use for a given subscription ID.

This script:
1. Loads config to get SPN overrides
2. Checks if subscription has an override
3. Returns the SPN to use (override or default)
"""

import sys
import argparse
import yaml
import os


def resolve_pipeline_variable(value):
    """
    Resolve pipeline variable syntax $(variableName) from environment.
    If not found in environment, return the literal string for Azure DevOps to resolve.
    """
    if not isinstance(value, str):
        return value
    
    if value.startswith('$(') and value.endswith(')'):
        var_name = value[2:-1]
        env_value = os.getenv(var_name)
        if env_value:
            return env_value
        return value
    return value


def get_spn_for_subscription(subscription_id, config, default_spn):
    """Get the SPN to use for a subscription (override or default)."""
    overrides = config.get('pipeline', {}).get('subscription_spn_overrides', {})
    
    # Check if subscription has an override
    if subscription_id in overrides:
        spn = overrides[subscription_id]
        # Resolve pipeline variable if present
        spn = resolve_pipeline_variable(spn)
        return spn
    
    # Use default SPN
    default_spn = resolve_pipeline_variable(default_spn)
    return default_spn


def main():
    parser = argparse.ArgumentParser(description='Find SPN for subscription')
    parser.add_argument('--subscription-id', required=True, help='Subscription ID')
    parser.add_argument('--config', required=True, help='Path to config YAML file')
    parser.add_argument('--default-spn', required=True, help='Default service connection name')
    parser.add_argument('--output', required=True, help='Output file path (will contain SPN name)')
    
    args = parser.parse_args()
    
    # Load config
    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)
    
    # Get SPN for subscription
    spn = get_spn_for_subscription(args.subscription_id, config, args.default_spn)
    
    # Resolve pipeline variable
    spn = resolve_pipeline_variable(spn)
    
    # Write to output file
    with open(args.output, 'w') as f:
        f.write(spn)
    
    print(f"Subscription {args.subscription_id} uses SPN: {spn}")


if __name__ == '__main__':
    main()


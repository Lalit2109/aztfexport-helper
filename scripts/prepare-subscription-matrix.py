#!/usr/bin/env python3
"""
Prepare matrix for selected subscriptions (comma-separated subscription IDs).

This script:
1. Parses comma-separated subscription IDs
2. For each subscription, finds its assigned SPN (override or default)
3. Creates matrix JSON with one entry per subscription
4. Outputs matrix for Azure DevOps pipeline
"""

import json
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


def create_matrix_json(subscription_ids, config, default_spn):
    """
    Create Azure DevOps matrix JSON format.
    One entry per subscription.
    """
    matrix = {}
    
    for sub_id in subscription_ids:
        sub_id = sub_id.strip()
        if not sub_id:
            continue
        
        # Get SPN for this subscription
        spn = get_spn_for_subscription(sub_id, config, default_spn)
        
        # Create matrix key from subscription ID (sanitize for valid identifier)
        matrix_key = f"Sub_{sub_id.replace('-', '_').replace(':', '_')}"
        
        # Ensure unique key
        base_key = matrix_key
        counter = 1
        while matrix_key in matrix:
            matrix_key = f"{base_key}_{counter}"
            counter += 1
        
        matrix[matrix_key] = {
            'subscriptionId': sub_id,
            'serviceConnection': spn  # Actual service connection name (resolved)
        }
    
    return matrix


def main():
    parser = argparse.ArgumentParser(description='Prepare subscription matrix')
    parser.add_argument('--subscription-ids', required=True, help='Comma-separated subscription IDs')
    parser.add_argument('--config', required=True, help='Path to config YAML file')
    parser.add_argument('--default-spn', required=True, help='Default service connection name')
    parser.add_argument('--output', required=True, help='Output matrix JSON file path')
    
    args = parser.parse_args()
    
    # Parse subscription IDs
    subscription_ids = [s.strip() for s in args.subscription_ids.split(',') if s.strip()]
    
    if not subscription_ids:
        print("Error: No subscription IDs provided", file=sys.stderr)
        sys.exit(1)
    
    # Load config
    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)
    
    # Resolve default SPN
    default_spn = resolve_pipeline_variable(args.default_spn)
    
    # Create matrix JSON
    matrix = create_matrix_json(subscription_ids, config, default_spn)
    
    if not matrix:
        print("Error: Failed to create matrix", file=sys.stderr)
        sys.exit(1)
    
    # Output matrix JSON (compressed, single line for Azure DevOps)
    with open(args.output, 'w') as f:
        json.dump(matrix, f, separators=(',', ':'))
    
    print(f"Created matrix with {len(matrix)} subscription(s):")
    for key, value in matrix.items():
        print(f"  {key}: {value['subscriptionId']} -> {value['serviceConnection']}")


if __name__ == '__main__':
    main()


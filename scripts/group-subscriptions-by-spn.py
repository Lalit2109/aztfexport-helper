#!/usr/bin/env python3
"""
Group discovered subscriptions by their assigned SPN (default or override).

This script:
1. Reads discovered subscriptions from JSON file
2. Loads config to get SPN overrides
3. Groups subscriptions by their assigned SPN (override or default)
4. Outputs matrix JSON for Azure DevOps pipeline
"""

import json
import sys
import argparse
import yaml
import os
from pathlib import Path


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


def group_subscriptions_by_spn(subscriptions, config, default_spn):
    """
    Group subscriptions by their assigned SPN.
    Returns dict: {spn_name: [subscription_ids]}
    """
    groups = {}
    
    for sub in subscriptions:
        sub_id = sub.get('id', '').strip()
        if not sub_id:
            continue
        
        # Get SPN for this subscription
        spn = get_spn_for_subscription(sub_id, config, default_spn)
        
        # Group by SPN
        if spn not in groups:
            groups[spn] = []
        
        groups[spn].append(sub_id)
    
    return groups


def create_matrix_json(groups, default_spn):
    """
    Create Azure DevOps matrix JSON format.
    Matrix keys must be valid identifiers (no special chars except underscore).
    """
    matrix = {}
    
    for spn, subscription_ids in groups.items():
        # Create a valid matrix key from SPN name
        # Replace special chars with underscore, ensure it starts with letter/underscore
        matrix_key = spn.replace('-', '_').replace('.', '_').replace('/', '_')
        if not matrix_key[0].isalpha() and matrix_key[0] != '_':
            matrix_key = 'SPN_' + matrix_key
        
        # Ensure unique key
        base_key = matrix_key
        counter = 1
        while matrix_key in matrix:
            matrix_key = f"{base_key}_{counter}"
            counter += 1
        
        matrix[matrix_key] = {
            'serviceConnection': spn,  # Actual service connection name (resolved)
            'subscriptions': subscription_ids
        }
    
    return matrix


def main():
    parser = argparse.ArgumentParser(description='Group subscriptions by SPN')
    parser.add_argument('--subscriptions', required=True, help='Path to subscriptions JSON file')
    parser.add_argument('--config', required=True, help='Path to config YAML file')
    parser.add_argument('--default-spn', required=True, help='Default service connection name')
    parser.add_argument('--output', required=True, help='Output matrix JSON file path')
    
    args = parser.parse_args()
    
    # Load subscriptions
    with open(args.subscriptions, 'r') as f:
        subscriptions = json.load(f)
    
    # Load config
    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)
    
    # Resolve default SPN
    default_spn = resolve_pipeline_variable(args.default_spn)
    
    # Group subscriptions by SPN
    groups = group_subscriptions_by_spn(subscriptions, config, default_spn)
    
    if not groups:
        print("Warning: No subscriptions to group", file=sys.stderr)
        sys.exit(1)
    
    # Create matrix JSON
    matrix = create_matrix_json(groups, default_spn)
    
    # Output matrix JSON (compressed, single line for Azure DevOps)
    with open(args.output, 'w') as f:
        json.dump(matrix, f, separators=(',', ':'))
    
    print(f"Created matrix with {len(matrix)} SPN group(s):")
    for key, value in matrix.items():
        print(f"  {key}: {len(value['subscriptions'])} subscription(s)")


if __name__ == '__main__':
    main()


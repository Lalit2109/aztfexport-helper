#!/usr/bin/env python3
"""
Discover subscriptions for Azure Pipeline matrix strategy
Uses default service connection to list subscriptions and filters by schedule/exclude config
"""

import sys
import json
import yaml
import subprocess
from pathlib import Path


def load_schedule_config(config_path: str = "azure-pipelines/schedule-config.yaml"):
    """Load schedule configuration"""
    config_file = Path(config_path)
    if not config_file.exists():
        return {}, []
    
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f) or {}
    
    schedules = config.get('schedules', {})
    exclude_list = config.get('exclude_subscriptions', [])
    
    return schedules, exclude_list


def get_subscriptions_from_azure():
    """Get all subscriptions accessible to the current Azure CLI account"""
    subscriptions = []
    
    try:
        result = subprocess.run(
            ['az', 'account', 'list', '--query', '[].{id:id, name:name, state:state}', '--output', 'json'],
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
            
            if sub_id and sub_state.lower() == 'enabled':
                subscriptions.append({
                    'id': sub_id,
                    'name': sub_name or sub_id
                })
        
        return subscriptions
        
    except Exception as e:
        print(f"Error listing subscriptions: {str(e)}", file=sys.stderr)
        return []


def filter_subscriptions(subscriptions, schedule_name=None, exclude_list=None):
    """Filter subscriptions based on schedule and exclude list"""
    exclude_list = exclude_list or []
    
    if schedule_name:
        schedules, _ = load_schedule_config()
        schedule_subs = schedules.get(schedule_name, {}).get('subscriptions', [])
        if schedule_subs:
            filtered = [s for s in subscriptions if s['id'] in schedule_subs or s['name'] in schedule_subs]
        else:
            filtered = []
    else:
        filtered = subscriptions
    
    excluded = [s for s in filtered if s['id'] in exclude_list or s['name'] in exclude_list]
    filtered = [s for s in filtered if s['id'] not in exclude_list and s['name'] not in exclude_list]
    
    return filtered, excluded


def generate_matrix(subscriptions):
    """Generate Azure Pipeline matrix format"""
    matrix = {}
    for sub in subscriptions:
        sub_id = sub['id']
        sub_name = sub['name']
        matrix[sub_id] = {
            'subscription_id': sub_id,
            'subscription_name': sub_name
        }
    return matrix


def main():
    """Main function"""
    schedule_name = sys.argv[1] if len(sys.argv) > 1 else None
    
    schedules, exclude_list = load_schedule_config()
    
    if schedule_name and schedule_name not in schedules:
        print(f"Error: Schedule '{schedule_name}' not found in schedule-config.yaml", file=sys.stderr)
        sys.exit(1)
    
    subscriptions = get_subscriptions_from_azure()
    
    if not subscriptions:
        print("No subscriptions found", file=sys.stderr)
        sys.exit(1)
    
    filtered, excluded = filter_subscriptions(subscriptions, schedule_name, exclude_list)
    
    if excluded:
        print(f"Excluded {len(excluded)} subscription(s):", file=sys.stderr)
        for sub in excluded:
            print(f"  - {sub['name']} ({sub['id']})", file=sys.stderr)
    
    if not filtered:
        print(f"No subscriptions to process for schedule '{schedule_name}'" if schedule_name else "No subscriptions to process", file=sys.stderr)
        sys.exit(1)
    
    matrix = generate_matrix(filtered)
    
    print(json.dumps(matrix, indent=2))
    
    print(f"\nFound {len(filtered)} subscription(s) to process", file=sys.stderr)
    for sub in filtered:
        print(f"  - {sub['name']} ({sub['id']})", file=sys.stderr)


if __name__ == "__main__":
    main()


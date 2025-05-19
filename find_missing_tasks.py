import yaml
import sqlite3
from pathlib import Path

def get_tasks_from_yaml(yaml_path: str) -> list[dict]:
    """Read tasks from YAML file."""
    with open(yaml_path, 'r') as f:
        data = yaml.safe_load(f)
    return data['tasks']

def get_tasks_from_db(db_path: str) -> dict[str, str]:
    """Get all tasks and their statuses from database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT task_id, status 
        FROM task_log 
    """)
    
    tasks = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return tasks

def find_missing_tasks(yaml_path: str, db_path: str) -> list[dict]:
    """Find tasks that are missing or failed in the database."""
    # Get all tasks from YAML
    all_tasks = get_tasks_from_yaml(yaml_path)
    # Use a set to track unique task IDs we've seen
    seen_task_ids = set()
    unique_tasks = []
    
    for task in all_tasks:
        if task['id'] not in seen_task_ids:
            seen_task_ids.add(task['id'])
            unique_tasks.append(task)
    
    # Get all tasks from database
    db_tasks = get_tasks_from_db(db_path)
    
    print("\nTasks in database:")
    for task_id, status in db_tasks.items():
        print(f"  - {task_id}: {status}")
    
    print("\nUnique tasks in YAML:")
    for task in unique_tasks:
        print(f"  - {task['id']}")
    
    # Find missing or failed tasks
    missing_tasks = []
    for task in unique_tasks:
        task_id = task['id']
        if task_id not in db_tasks:
            print(f"\nTask {task_id} not found in database")
            missing_tasks.append(task)
        elif db_tasks[task_id] != 'COMPLETED':
            print(f"\nTask {task_id} has status {db_tasks[task_id]}")
            missing_tasks.append(task)
    
    return missing_tasks

def create_missing_tasks_yaml(missing_tasks: list[dict], output_path: str):
    """Create a new YAML file with just the missing tasks."""
    yaml_data = {
        'execution': {
            'mode': 'local_parallel'
        },
        'tasks': missing_tasks
    }
    
    with open(output_path, 'w') as f:
        yaml.dump(yaml_data, f, default_flow_style=False)

if __name__ == "__main__":
    yaml_path = "sweep_chunk_2_of_3.yml"
    db_path = "runs_chunk_2_of_3.sqlite"
    output_path = "missing_tasks.yml"
    
    print(f"Reading tasks from {yaml_path}")
    print(f"Checking completion status in {db_path}")
    
    missing_tasks = find_missing_tasks(yaml_path, db_path)
    
    print(f"\nFound {len(missing_tasks)} missing or failed tasks:")
    for task in missing_tasks:
        print(f"  - {task['id']}")
    
    create_missing_tasks_yaml(missing_tasks, output_path)
    print(f"\nCreated {output_path} with missing tasks") 
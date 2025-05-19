import sqlite3
from datetime import datetime


def add_missing_tasks(db_path: str):
    """Add the two missing tasks to the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get the current timestamp
    timestamp = datetime.now().isoformat()

    # The two tasks we want to add
    tasks = [
        {
            'run_id': 'chunk_2_of_3',
            'task_id': '13_formamide_dimer_jun-cc-pVDZ',
            'attempt_number': 1,
            'status': 'PENDING',
            'monomer_a_xyz': 'data/s22_split/13_formamide_dimer_a.xyz',
            'monomer_b_xyz': 'data/s22_split/13_formamide_dimer_b.xyz',
            'basis_set': 'jun-cc-pVDZ',
            'method': 'sapt0',
            'timestamp_utc': timestamp
        },
        {
            'run_id': 'chunk_2_of_3',
            'task_id': '13_formamide_dimer_jun-cc-pVDZ',
            'attempt_number': 2,
            'status': 'PENDING',
            'monomer_a_xyz': 'data/s22_split/13_formamide_dimer_a.xyz',
            'monomer_b_xyz': 'data/s22_split/13_formamide_dimer_b.xyz',
            'basis_set': 'jun-cc-pVDZ',
            'method': 'sapt0',
            'timestamp_utc': timestamp
        }
    ]

    # Add each task
    for task in tasks:
        cursor.execute("""
            INSERT INTO task_log (
                run_id, task_id, attempt_number, status,
                monomer_a_xyz, monomer_b_xyz, basis_set, method,
                timestamp_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task['run_id'],
            task['task_id'],
            task['attempt_number'],
            task['status'],
            task['monomer_a_xyz'],
            task['monomer_b_xyz'],
            task['basis_set'],
            task['method'],
            task['timestamp_utc']
        ))

    conn.commit()
    conn.close()

    print(f"Added {len(tasks)} tasks to {db_path}")

if __name__ == "__main__":
    db_path = "runs_chunk_2_of_3.sqlite"
    add_missing_tasks(db_path)

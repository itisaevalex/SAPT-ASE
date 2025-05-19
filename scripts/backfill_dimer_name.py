#!/usr/bin/env python
"""
Back-fill dimer_name in an existing runs.sqlite without recomputing jobs.

1. adds column task_log.dimer_name  (if missing)
2. derives canonical names
3. updates both task_log and results
"""

import argparse, hashlib, json, re, sqlite3, sys, pathlib, yaml
from collections import defaultdict
from typing import Dict

# ---------- helpers ----------------------------------------------------------

def md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()

def load_hash_map(path: pathlib.Path) -> Dict[str, str]:
    with open(path) as f:
        return yaml.safe_load(f)  # {md5hash: "04_ammonia_dimer"}

# ---------- core -------------------------------------------------------------

def main(dbfile: pathlib.Path, *, hash_map=None, regex=None):
    if not dbfile.exists():
        sys.exit(f"DB file {dbfile} not found")

    conn = sqlite3.connect(dbfile)
    cur  = conn.cursor()

    # 1️⃣  ensure the column exists
    cur.execute("PRAGMA table_info(task_log)")
    if "dimer_name" not in {row[1] for row in cur.fetchall()}:
        print("Adding dimer_name column to task_log …")
        cur.execute("ALTER TABLE task_log ADD COLUMN dimer_name TEXT")
        conn.commit()

    # 2️⃣  fetch rows still missing the value
    cur.execute("""
        SELECT log_id, task_id, monomer_a_xyz, monomer_b_xyz
        FROM task_log
        WHERE dimer_name IS NULL
    """)
    rows = cur.fetchall()
    if not rows:
        print("Nothing to update – every row in task_log already has dimer_name.")
        # We still might need to update results table, so continue
    else:
        print(f"Found {len(rows)} rows in task_log missing dimer_name.")

    updates = []                   # [(dimer_name, log_id), …]
    missing = defaultdict(int)     # stats

    for log_id, task_id, xyz_a, xyz_b in rows:
        name = None
        if hash_map and xyz_a is not None and xyz_b is not None:
            h = md5(xyz_a + xyz_b)
            name = hash_map.get(h)
            if name is None:
                missing["hash_lookup_failed"] += 1
        elif hash_map and (xyz_a is None or xyz_b is None):
            missing["hash_xyz_missing"] += 1
            
        if name is None and regex:
            if task_id is not None:
                m = regex.search(task_id)
                if m:
                    name = m.group("dimer")
                else:
                    missing["regex_no_match"] += 1
            else:
                missing["regex_task_id_missing"] += 1
        
        if name:
            updates.append((name, log_id))
        elif not hash_map or (xyz_a is None or xyz_b is None and regex is None): # if only hashmap was provided and xyz was missing, or neither method could determine name
            missing["unresolved"] +=1

    if updates:
        print(f" → Will attempt to update {len(updates)} rows in task_log with derived dimer_name.")
    if missing:
        print(" ! Statistics for rows in task_log where dimer_name could not be derived:", dict(missing))

    # 3️⃣  bulk-update task_log  (dimer_name is not part of PRIMARY KEY)
    if updates:
        cur.executemany(
            "UPDATE task_log SET dimer_name = ? WHERE log_id = ?",
            updates,
        )
        conn.commit()
        print(f"Updated {cur.rowcount} rows in task_log.")
    else:
        print("No rows in task_log were updated with new dimer_names.")

    # 4️⃣  copy the dimer_name into results (joined on run_id + task_id)
    cur.execute("PRAGMA table_info(results)")
    results_has_dimer_name = "dimer_name" in {row[1] for row in cur.fetchall()}
    if not results_has_dimer_name:
        print("Adding dimer_name column to results table …")
        cur.execute("ALTER TABLE results ADD COLUMN dimer_name TEXT")
        conn.commit()

    # Update results where dimer_name is NULL, using values from task_log
    # This ensures we only update rows that need it and uses the (potentially) newly populated dimer_name from task_log
    update_results_query = """
        UPDATE results
        SET dimer_name = (
            SELECT tl.dimer_name
            FROM task_log tl
            WHERE tl.run_id = results.run_id
              AND tl.task_id = results.task_id
              AND tl.dimer_name IS NOT NULL
            ORDER BY tl.log_id DESC -- In case of multiple task_log entries for same task_id (e.g. retries), prefer latest
            LIMIT 1
        )
        WHERE results.dimer_name IS NULL
          AND EXISTS (
            SELECT 1 
            FROM task_log tl 
            WHERE tl.run_id = results.run_id 
              AND tl.task_id = results.task_id 
              AND tl.dimer_name IS NOT NULL
            )
    """
    cur.execute(update_results_query)
    conn.commit()
    print(f"Updated {cur.rowcount} rows in results table with dimer_name from task_log.")
    
    print("Backfill process completed.")
    conn.close()

# ---------- CLI --------------------------------------------------------------

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=
        "Back-fill dimer_name in an existing runs.sqlite. "
        "Adds dimer_name column to task_log and results if missing. "
        "Updates rows where dimer_name is NULL using hash map or regex."
    )
    ap.add_argument("--db", type=pathlib.Path, required=True, help="Path to the SQLite database file (e.g., runs/runs.sqlite)")
    ap.add_argument("--hash-map", type=pathlib.Path, help="Path to YAML mapping file: md5(monomer_a_xyz + monomer_b_xyz) ➜ canonical_dimer_name")
    ap.add_argument("--regex", help="Regex pattern with a named group 'dimer' (e.g., '^(?P<dimer>\d{2}_[^_]+_[^_]+)') to extract name from task_id as a fallback or primary method.")
    args = ap.parse_args()

    compiled_regex = re.compile(args.regex, re.IGNORECASE) if args.regex else None
    hashmap_data  = load_hash_map(args.hash_map) if args.hash_map else None
    
    if not (hashmap_data or compiled_regex):
        ap.error("Error: Please provide at least --hash-map or --regex.")
        sys.exit(1)
        
    main(args.db, hash_map=hashmap_data, regex=compiled_regex)

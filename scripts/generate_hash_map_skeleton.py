#!/usr/bin/env python
"""
Generates a skeleton YAML file for mapping XYZ content hashes to canonical dimer names.

1. Connects to the SQLite database.
2. Extracts unique (monomer_a_xyz, monomer_b_xyz) pairs from task_log.
3. Hashes the concatenated XYZ strings.
4. Writes XYZ content to individual files in tmp_xyz/ (for inspection).
5. Creates a data/dimer_hash_map.yml with hashes mapped to "PLEASE_FILL_ME_IN".
"""

import sqlite3
import pathlib
import hashlib
import textwrap
import yaml
import os

# Configuration
DB_FILE = pathlib.Path("..", "runs", "runs.sqlite").resolve() # Assuming script is in 'scripts' and db in 'runs'
OUT_DIR = pathlib.Path("..", "tmp_xyz").resolve()      # Temporary XYZ files for inspection
MAP_FILE = pathlib.Path("..", "data", "dimer_hash_map.yml").resolve() # Output skeleton YAML map

def main():
    if not DB_FILE.exists():
        print(f"ERROR: Database file not found at {DB_FILE}")
        print("Please ensure the path is correct and the database exists.")
        return

    OUT_DIR.mkdir(exist_ok=True)
    MAP_FILE.parent.mkdir(exist_ok=True) # Ensure 'data' directory exists

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    print(f"Querying database: {DB_FILE}")
    cur.execute("""
        SELECT DISTINCT monomer_a_xyz, monomer_b_xyz
        FROM task_log
        WHERE monomer_a_xyz IS NOT NULL AND monomer_b_xyz IS NOT NULL
    """)

    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("No non-NULL monomer_a_xyz, monomer_b_xyz pairs found in task_log.")
        return

    print(f"Found {len(rows)} unique XYZ pairs.")

    mapping = {}
    xyz_files_written = 0
    for xyz_a, xyz_b in rows:
        # Ensure they are strings, even if None (though query filters NULLs)
        s_xyz_a = xyz_a if xyz_a is not None else ""
        s_xyz_b = xyz_b if xyz_b is not None else ""
        
        combo = s_xyz_a + "\n---\n" + s_xyz_b # Added a separator for clarity in dumped files
        h = hashlib.md5(combo.encode('utf-8')).hexdigest()
        
        fname = OUT_DIR / f"{h}.xyz"
        # Store for manual inspection (optional)
        try:
            with fname.open("w", encoding='utf-8') as f:
                f.write(textwrap.dedent(f"""# MD5 Hash: {h}
# --- Monomer A ---
{s_xyz_a}

# --- Monomer B ---
{s_xyz_b}
"""))
            xyz_files_written += 1
        except Exception as e:
            print(f"Warning: Could not write temporary XYZ file {fname}: {e}")

        # Placeholder value – user will edit this in the YAML file
        mapping[h] = "PLEASE_FILL_ME_IN"

    if mapping:
        try:
            with MAP_FILE.open("w", encoding='utf-8') as f_yaml:
                yaml.safe_dump(mapping, f_yaml, sort_keys=True)
            print(f"Successfully wrote {len(mapping)} entries to skeleton map: {MAP_FILE}")
            if xyz_files_written > 0:
                 print(f"Wrote {xyz_files_written} temporary XYZ files to: {OUT_DIR}")
        except Exception as e:
            print(f"ERROR: Could not write YAML mapping file {MAP_FILE}: {e}")
    else:
        print("No mapping entries generated.")

if __name__ == "__main__":
    main()

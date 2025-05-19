#!/usr/bin/env python3
"""
Generates a skeleton YAML file mapping MD5 hashes of concatenated
(monomer_a_xyz, monomer_b_xyz) strings to guessed dimer names.

1. Connects to the SQLite database.
2. Fetches unique (monomer_a_xyz, monomer_b_xyz) pairs and an example task_id.
3. Guesses dimer name from task_id using regex.
4. Hashes the concatenated XYZ strings (from DB).
5. Writes XYZ content and guessed names to individual files in tmp_xyz/ (for inspection).
6. Creates a data/dimer_hash_map.yml with hashes mapped to guessed names or a placeholder.
"""

import sqlite3
import pathlib
import hashlib
import re
import textwrap
import yaml
# import os # Not strictly needed for this version

# Configuration
DB_PATH = pathlib.Path(__file__).resolve().parent.parent / "runs" / "runs.sqlite"
OUT_YAML_FILE = pathlib.Path(__file__).resolve().parent.parent / "data" / "dimer_hash_map.yml"
OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "tmp_xyz"

PLACEHOLDER_NAME = "MANUAL_REVIEW_NEEDED"
# Regex to capture dimer names like '01_Helium_dimer' or '03_adenine_thymine_wc'
# from a task_id like '01_Helium_dimer_aug-cc-pVDZ' or '03_adenine_thymine_wc_HF_SAPT0_jun-cc-pVDZ'
DIMER_NAME_REGEX = r"^(?P<dimer_name>\d{2}_(?:[A-Za-z0-9]+_)*[A-Za-z0-9]+)(?:_|$)"

def get_unique_xyz_and_task_ids_from_db(db_path):
    """
    Fetches unique pairs of (monomer_a_xyz, monomer_b_xyz)
    and an example task_id for each.
    """
    unique_xyz_data = {}  # Using dict to ensure one task_id per unique pair
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # Using MIN(task_id) to get a deterministic task_id for each group.
        # Filter out entries where XYZ data might be NULL, though backfill script would also skip these.
        query = """
            SELECT
                monomer_a_xyz,
                monomer_b_xyz,
                MIN(task_id) as example_task_id
            FROM task_log
            WHERE monomer_a_xyz IS NOT NULL AND monomer_b_xyz IS NOT NULL
            GROUP BY monomer_a_xyz, monomer_b_xyz
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        for row_a_xyz, row_b_xyz, row_task_id in rows:
            pair = (row_a_xyz, row_b_xyz)
            unique_xyz_data[pair] = row_task_id

    except sqlite3.Error as e:
        print(f"Database error: {e}")
    except Exception as e:
        print(f"Exception in get_unique_xyz_and_task_ids_from_db: {e}")
    finally:
        if conn:
            conn.close()
    print(f"Found {len(unique_xyz_data)} unique non-NULL XYZ configurations in the database.")
    return [(pair[0], pair[1], task_id) for pair, task_id in unique_xyz_data.items()]

def main():
    if not DB_PATH.exists():
        print(f"ERROR: Database file not found at {DB_PATH}")
        print("Please ensure the path is correct and the database exists.")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_YAML_FILE.parent.mkdir(parents=True, exist_ok=True) # Ensure 'data' directory exists

    unique_xyz_data_list = get_unique_xyz_and_task_ids_from_db(DB_PATH)
    yaml_data = {}
    # xyz_files_written = 0 # Not strictly needed for counting if we just count files at the end
    guessed_names_count = 0

    if not unique_xyz_data_list:
        print("No unique non-NULL XYZ configurations found. Exiting.")
        return

    print(f"Processing {len(unique_xyz_data_list)} unique XYZ configurations to generate hash map skeleton...")

    for xyz_a, xyz_b, task_id in unique_xyz_data_list:
        # These should be non-null due to SQL query, but defense in depth
        s_xyz_a = xyz_a if xyz_a is not None else ""
        s_xyz_b = xyz_b if xyz_b is not None else ""
        
        # Hash for the YAML map key MUST match backfill_dimer_name.py: direct concatenation
        current_hash = hashlib.md5((s_xyz_a + s_xyz_b).encode('utf-8')).hexdigest()

        guessed_name = PLACEHOLDER_NAME
        if task_id:
            match = re.search(DIMER_NAME_REGEX, task_id)
            if match:
                extracted_name_candidate = match.group("dimer_name")
                # Ensure it's not just an empty string or something very short if regex is too greedy
                if extracted_name_candidate and len(extracted_name_candidate) > 2: 
                    guessed_name = extracted_name_candidate
                    # Only count if it's different from the placeholder
                    if guessed_name != PLACEHOLDER_NAME: # Check if regex actually produced something new
                         # This logic can be tricky if placeholder itself is a valid guess
                         # So, we count actual successful extractions that are not the placeholder
                         is_new_guess = True # Assume it's a new guess
                         if current_hash in yaml_data and yaml_data[current_hash] != PLACEHOLDER_NAME:
                            is_new_guess = False # Already had a non-placeholder guess
                         if is_new_guess: guessed_names_count +=1
            else:
                print(f"Warning: Could not parse dimer name from task_id: '{task_id}' for hash {current_hash}")
        
        fname = OUT_DIR / f"{current_hash}.xyz"
        # Write inspection file (always overwrite to ensure it's up-to-date)
        try:
            with fname.open("w", encoding='utf-8') as f:
                f.write(textwrap.dedent(f"""# DB-Derived MD5 Hash (Key for YAML): {current_hash}
# Example task_id from DB: {task_id if task_id else 'N/A'}
# Guessed Dimer Name (from task_id regex '{DIMER_NAME_REGEX}'): {guessed_name}
# This hash was generated from direct concatenation of Monomer A XYZ and Monomer B XYZ from the database.

# --- Monomer A (from DB) ---
{s_xyz_a}

# --- Monomer B (from DB) ---
{s_xyz_b}
"""))
        except Exception as e:
            print(f"Error writing inspection file {fname}: {e}")

        # Add to YAML data, or update if new guess is better than placeholder
        if current_hash not in yaml_data or (yaml_data[current_hash] == PLACEHOLDER_NAME and guessed_name != PLACEHOLDER_NAME):
            yaml_data[current_hash] = guessed_name

    # Write the YAML file
    try:
        with OUT_YAML_FILE.open("w", encoding='utf-8') as f_yaml: # Corrected variable name
            yaml.dump(yaml_data, f_yaml, sort_keys=True, default_flow_style=False, indent=2)
        print(f"\nSuccessfully wrote {len(yaml_data)} entries to {OUT_YAML_FILE}")
        print(f"Successfully guessed {guessed_names_count} dimer names from task_ids.")
        # A more robust way to count files actually written now
        current_files_in_out_dir = len(list(OUT_DIR.glob("*.xyz")))
        print(f"Wrote/updated {current_files_in_out_dir} XYZ inspection files to {OUT_DIR}")

    except Exception as e:
        print(f"Error writing YAML file {OUT_YAML_FILE}: {e}") # Corrected variable name

if __name__ == "__main__":
    main()

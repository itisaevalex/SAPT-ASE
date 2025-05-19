import os
import re
import sqlite3


def extract_monomer_names(task_id: str) -> tuple[str, str]:
    """Extract monomer names from task_id.

    Example:
        task_id = "08_benzene_dimer_tshape_jun-cc-pVTZ"
        returns: ("08_benzene_dimer_tshape_a.xyz", "08_benzene_dimer_tshape_b.xyz")
    """
    # Remove basis set suffix
    base_name = re.sub(r"_[a-z]+-[a-z]+-[A-Z]+$", "", task_id)

    # For benzene dimer, indole-benzene, etc.
    if "dimer" in base_name or "stack" in base_name:
        return f"{base_name}_a.xyz", f"{base_name}_b.xyz"

    # For benzene-hcn, benzene-water, etc.
    parts = base_name.split("_")
    if len(parts) >= 3:
        # Extract the two molecules
        mol1 = "_".join(parts[:-1])  # e.g., "09_benzene"
        mol2 = parts[-1]  # e.g., "hcn"
        return f"{mol1}_{mol2}_a.xyz", f"{mol1}_{mol2}_b.xyz"

    raise ValueError(f"Could not parse monomer names from task_id: {task_id}")


def read_xyz_file(filepath: str) -> str:
    """Read XYZ file and return its contents as a string."""
    with open(filepath, "r") as f:
        return f.read()


def fix_xyz_strings(db_path: str, xyz_dir: str):
    """Fix XYZ strings in the database by reading original files."""
    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get all task_ids and their current XYZ strings
    cursor.execute(
        """
        SELECT task_id, monomer_a_xyz, monomer_b_xyz
        FROM task_log
        WHERE status = 'COMPLETED'
    """
    )

    # Process each task
    for task_id, current_a_xyz, current_b_xyz in cursor.fetchall():
        try:
            # Extract monomer filenames
            monomer_a_file, monomer_b_file = extract_monomer_names(task_id)

            # Read original XYZ files
            a_xyz_path = os.path.join(xyz_dir, monomer_a_file)
            b_xyz_path = os.path.join(xyz_dir, monomer_b_file)

            if not os.path.exists(a_xyz_path) or not os.path.exists(b_xyz_path):
                print(f"Warning: Could not find XYZ files for task {task_id}")
                print(f"  Looking for: {a_xyz_path} and {b_xyz_path}")
                continue

            new_a_xyz = read_xyz_file(a_xyz_path)
            new_b_xyz = read_xyz_file(b_xyz_path)

            # Update database
            cursor.execute(
                """
                UPDATE task_log
                SET monomer_a_xyz = ?, monomer_b_xyz = ?
                WHERE task_id = ?
            """,
                (new_a_xyz, new_b_xyz, task_id),
            )

            print(f"Updated XYZ strings for task {task_id}")

        except Exception as e:
            print(f"Error processing task {task_id}: {e}")
            continue

    # Commit changes and close
    conn.commit()
    conn.close()


if __name__ == "__main__":
    # Get database path from command line or use default
    import sys

    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = "runs_chunk_2_of_3.sqlite"

    # XYZ files directory
    xyz_dir = "data/s22_split"

    print(f"Fixing XYZ strings in database {db_path}")
    print(f"Reading original XYZ files from {xyz_dir}")

    fix_xyz_strings(db_path, xyz_dir)
    print("Done!")

#!/usr/bin/env python
"""
Emit a sweep.yml containing one SaptTask per (monomer pair, basis).
Usage: python scripts/build_sweep_yaml.py --split-xyz-dir data/s22_split --basis-list "" --out sweep.yml
If --basis-list omitted, uses the 12-basis list from the script.
Expects monomer files named like '*_a.xyz' and '*_b.xyz' in the directory.
"""
import argparse
import pathlib
import textwrap  # Import textwrap

import yaml

# Default list if --basis-list is empty
# TODO: Ensure this list aligns with project goals / ADR-0005 if it exists
BASIS_DEFAULT = [
    "jun-cc-pVDZ",
    "aug-cc-pVDZ",
    "jun-cc-pVDZ",
    "jun-cc-pVTZ",
    "aug-cc-pVTZ",
    "jun-cc-pVTZ",
    # "jun-cc-pVQZ", # Temporarily removed for CI
    # "aug-cc-pVQZ", # Temporarily removed for CI
    "def2-SVPD",
    "def2-TZVPD",
    # "def2-QZVPD", # Temporarily removed for CI
    "def2-TZVPPD",
]


def main():
    p = argparse.ArgumentParser(
        description=textwrap.dedent(__doc__), formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--split-xyz-dir",
        required=True,
        type=pathlib.Path,
        help="Directory containing pre-split monomer .xyz files (e.g., *_a.xyz, *_b.xyz).",
    )
    p.add_argument(
        "--basis-list",
        default="",
        help="Comma-separated list of basis sets. Defaults to built-in list.",
    )
    p.add_argument("--out", required=True, type=pathlib.Path, help="Output YAML file path.")
    p.add_argument("--monomer-a-charge", type=int, default=0)
    p.add_argument("--monomer-a-mult", type=int, default=1)
    p.add_argument("--monomer-b-charge", type=int, default=0)
    p.add_argument("--monomer-b-mult", type=int, default=1)
    p.add_argument("--method", default="sapt0", help="SAPT method to use.")
    p.add_argument(
        "--total-chunks",
        type=int,
        default=1,
        help="Total number of chunks to divide the tasks into. Default is 1 (no chunking).",
    )
    p.add_argument(
        "--chunk-index",
        type=int,
        default=0,
        help="0-based index of the current chunk to generate. Default is 0.",
    )
    p.add_argument(
        "--master-db-path",
        type=pathlib.Path,
        default=None,
        help="Optional path to a master SQLite database. If provided, tasks already completed in this DB will be skipped.",
    )

    args = p.parse_args()

    if not args.split_xyz_dir.is_dir():
        raise FileNotFoundError(f"Split XYZ directory not found: {args.split_xyz_dir}")

    bases = [b.strip() for b in args.basis_list.split(",") if b.strip()] or BASIS_DEFAULT

    # Find all monomer A files
    monomer_a_files = sorted(args.split_xyz_dir.glob("*_a.xyz"))

    if not monomer_a_files:
        print(f"Warning: No '*_a.xyz' files found in {args.split_xyz_dir}")
        # Decide if this should be an error

    tasks = []
    num_pairs = 0  # Counter for valid pairs
    # Iterate through monomer A files to find corresponding monomer B files
    for file_a in monomer_a_files:
        # Construct the expected filename for monomer B
        base_name = file_a.name.replace("_a.xyz", "")
        file_b = args.split_xyz_dir / f"{base_name}_b.xyz"

        if not file_b.is_file():
            print(
                f"Warning: Corresponding monomer B file not found for {file_a.name}. Skipping dimer {base_name}."
            )
            continue

        num_pairs += 1  # Found a valid pair

        # Create tasks for each basis set for this monomer pair
        for basis in bases:
            # Use the base name (without _a/_b suffix) for the task ID
            dimer_name = base_name.replace(" ", "_")  # Sanitize name
            task_id = f"{dimer_name}_{basis}"

            # Define monomers using relative paths from the repository root
            # The Path objects file_a and file_b already hold this.
            tasks.append(
                {
                    "id": task_id,
                    "basis_set": basis,
                    "method": args.method,
                    "monomer_a": {
                        "file": str(file_a),
                        "charge": args.monomer_a_charge,
                        "multiplicity": args.monomer_a_mult,
                    },
                    "monomer_b": {
                        "file": str(file_b),
                        "charge": args.monomer_b_charge,
                        "multiplicity": args.monomer_b_mult,
                    },
                }
            )

    # --- Potentially filter tasks based on master_db_path ---
    if args.master_db_path and args.master_db_path.exists():
        print(f"Querying master database: {args.master_db_path} to filter completed tasks...")
        try:
            # This requires saptase to be importable in the environment where this script runs
            from saptase.core.logdb import LogDb

            logdb = LogDb(args.master_db_path)
            uncompleted_tasks = []
            completed_count = 0
            for task_def in tasks:
                # Reconstruct necessary info for get_cached_result
                # This assumes file paths are sufficient and LogDb can handle them
                # or that we'd need to load XYZ content here if LogDb requires full Molecule string.
                # For now, assuming LogDb's get_cached_result can work with what's available or
                # that it's robust to partial info if it's just checking by task_id components.

                # To properly check cache, we need the XYZ content.
                mon_a_xyz = pathlib.Path(task_def["monomer_a"]["file"]).read_text()
                mon_b_xyz = pathlib.Path(task_def["monomer_b"]["file"]).read_text()

                cached_result = logdb.get_cached_result(
                    monomer_a_xyz=mon_a_xyz,
                    monomer_b_xyz=mon_b_xyz,
                    basis_set=task_def["basis_set"],
                    method=task_def["method"],
                )
                if cached_result and cached_result.success:
                    # print(f"Task {task_def['id']} found as completed in master DB. Skipping.")
                    completed_count += 1
                else:
                    uncompleted_tasks.append(task_def)

            if completed_count > 0:
                print(
                    f"Skipped {completed_count} tasks found as completed in {args.master_db_path}."
                )
            tasks = uncompleted_tasks  # Update tasks to only those not completed
            logdb.close()

        except ImportError:
            print(
                "Warning: Could not import saptase.core.logdb. Skipping filtering based on master_db_path. Ensure saptase is in PYTHONPATH."
            )
        except Exception as e:
            print(
                f"Warning: Error during database query for task filtering: {e}. Proceeding without filtering."
            )

    # --- Chunking logic ---
    tasks_for_this_chunk = []
    if args.total_chunks > 1:
        if not (0 <= args.chunk_index < args.total_chunks):
            raise ValueError(
                f"chunk_index ({args.chunk_index}) must be between 0 and total_chunks-1 ({args.total_chunks - 1})."
            )

        num_total_tasks = len(tasks)
        chunk_size = (num_total_tasks + args.total_chunks - 1) // args.total_chunks
        start_index = args.chunk_index * chunk_size
        end_index = min((args.chunk_index + 1) * chunk_size, num_total_tasks)

        tasks_for_this_chunk = tasks[start_index:end_index]
        print(
            f"Selected chunk {args.chunk_index + 1}/{args.total_chunks}: Tasks {start_index + 1}-{end_index} of {num_total_tasks} total (after potential DB filter)."
        )
    else:
        tasks_for_this_chunk = tasks  # No chunking, use all (filtered) tasks
        print(f"No chunking requested. Using all {len(tasks)} tasks (after potential DB filter).")

    # Structure matches SAPTASE expected input YAML format
    job_config = {
        "execution": {"mode": "local_parallel"},  # This is informational, mode is set by CLI
        "tasks": tasks_for_this_chunk,  # Use the selected chunk
    }

    try:
        # Use safe_dump for better YAML practices
        yaml_output = yaml.safe_dump(job_config, sort_keys=False)
        args.out.write_text(yaml_output)
        print(f"Generated {len(tasks_for_this_chunk)} tasks to {args.out}")
    except Exception as e:
        print(f"Error writing YAML file {args.out}: {e}")
        # Decide if you want to sys.exit(1) here


if __name__ == "__main__":
    # Added basic import error handling for PyYAML
    try:
        import pathlib  # Ensure pathlib is imported for type hints if not already top-level for script logic
        import textwrap  # Ensure textwrap is imported here as well

        import yaml
    except ImportError:
        print("Error: PyYAML is required to run this script. Install with: pip install pyyaml")
        exit(1)
    main()

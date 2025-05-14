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

    # Structure matches SAPTASE expected input YAML format
    job_config = {
        "execution": {"mode": "local_parallel"},  # This is informational, mode is set by CLI
        "tasks": tasks,
    }

    try:
        # Use safe_dump for better YAML practices
        yaml_output = yaml.safe_dump(job_config, sort_keys=False)
        args.out.write_text(yaml_output)
        print(
            f"Generated {len(tasks)} tasks "
            f"({num_pairs} dimers x {len(bases)} bases) to {args.out}"
        )
    except Exception as e:
        print(f"Error writing YAML file {args.out}: {e}")
        # Decide if you want to sys.exit(1) here


if __name__ == "__main__":
    # Added basic import error handling for PyYAML
    try:
        import textwrap  # Ensure textwrap is imported here as well

        import yaml
    except ImportError:
        print("Error: PyYAML is required to run this script. Install with: pip install pyyaml")
        exit(1)
    main()

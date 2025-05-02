 #!/usr/bin/env python
"""
Emit a sweep.yml containing one SaptTask per (xyz,basis).
Usage: python scripts/build_sweep_yaml.py --xyz-dir s22_xyz --basis-list "" --out sweep.yml
If --basis-list omitted, uses the 12-basis list from ADR-0005.
"""
import argparse
import itertools
import pathlib

import yaml

# Default list if --basis-list is empty
# TODO: Ensure this list aligns with project goals / ADR-0005 if it exists
BASIS_DEFAULT = [
    "jun-cc-pVDZ", "aug-cc-pVDZ", "jul-cc-pVDZ",
    "jun-cc-pVTZ", "aug-cc-pVTZ", "jul-cc-pVTZ",
    "jun-cc-pVQZ", "aug-cc-pVQZ",
    "def2-SVPD", "def2-TZVPD", "def2-QZVPD", "def2-ma-SVPD"
]

def main():
    p = argparse.ArgumentParser(description=textwrap.dedent(__doc__),
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--xyz-dir", required=True, type=pathlib.Path,
                   help="Directory containing .xyz files for dimers.")
    p.add_argument("--basis-list", default="",
                   help="Comma-separated list of basis sets. Defaults to built-in list.")
    p.add_argument("--out", required=True, type=pathlib.Path,
                   help="Output YAML file path.")
    p.add_argument("--monomer-a-charge", type=int, default=0)
    p.add_argument("--monomer-a-mult", type=int, default=1)
    p.add_argument("--monomer-b-charge", type=int, default=0)
    p.add_argument("--monomer-b-mult", type=int, default=1)
    p.add_argument("--method", default="sapt0", help="SAPT method to use.")

    args = p.parse_args()

    if not args.xyz_dir.is_dir():
        raise FileNotFoundError(f"XYZ directory not found: {args.xyz_dir}")

    bases = [b.strip() for b in args.basis_list.split(",") if b.strip()] or BASIS_DEFAULT
    xyz_files = sorted(args.xyz_dir.glob("*.xyz"))

    if not xyz_files:
        print(f"Warning: No .xyz files found in {args.xyz_dir}")
        # Decide if this should be an error

    tasks = []
    for xyz_file, basis in itertools.product(xyz_files, bases):
        # Use filename without extension as part of the task ID
        dimer_name = xyz_file.stem.replace(" ", "_") # Sanitize name
        task_id = f"{dimer_name}_{basis}"

        # Assume the XYZ file contains the full dimer
        # SAPTASE needs monomer definitions. This script currently duplicates
        # the whole XYZ for both monomers. Adjust if your XYZ files are different
        # or if SAPTASE handles dimer splitting internally based on keywords.
        tasks.append({
            "id": task_id,
            "basis_set": basis,
            "method": args.method,
            # Define monomers using the file path
            "monomer_a": {
                "file": str(xyz_file),
                "charge": args.monomer_a_charge,
                "multiplicity": args.monomer_a_mult
            },
            "monomer_b": {
                "file": str(xyz_file),
                "charge": args.monomer_b_charge,
                "multiplicity": args.monomer_b_mult
            },
            # Add any default keywords if needed
            # "additional_keywords": {
            #     "some_psi4_option": True
            # }
        })

    # Structure matches SAPTASE expected input YAML format
    job_config = {
        "execution": {
            "mode": "local_parallel" # This is informational, mode is set by CLI
        },
        "tasks": tasks
    }

    try:
        # Use safe_dump for better YAML practices
        yaml_output = yaml.safe_dump(job_config, sort_keys=False)
        args.out.write_text(yaml_output)
        print(f"Wrote {len(tasks)} tasks to {args.out}")
    except Exception as e:
        print(f"Error writing YAML file {args.out}: {e}")
        # Decide if you want to sys.exit(1) here

if __name__ == "__main__":
    # Added basic import error handling for PyYAML
    try:
        import yaml
        import textwrap # Needed for description formatting
    except ImportError:
        print("Error: PyYAML is required to run this script. Install with: pip install pyyaml")
        exit(1)
    main()

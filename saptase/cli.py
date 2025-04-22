# saptase/cli.py
"""
Command-line interface for the SAPTASE workflow manager.
"""

import argparse
import sys
import json
import numpy as np # Needed for Molecule coordinates
from typing import List, Optional

# Import necessary components
from .core.interop.yaml import load_config
from .core.models import Molecule, SaptTask
from .core.orchestrator import run_adaptive_workflow


def _create_molecule(mol_data: dict) -> Molecule:
    """Helper to create a Molecule object from config data."""
    if not mol_data or "symbols" not in mol_data or "coordinates" not in mol_data:
        raise ValueError("Molecule definition missing 'symbols' or 'coordinates'.")
    # Convert coordinates to numpy array
    coords = np.array(mol_data["coordinates"], dtype=float)
    if coords.ndim != 2 or coords.shape[1] != 3:
         raise ValueError(f"Coordinates must be a list of [x, y, z] lists/tuples. Got shape {coords.shape}")
    return Molecule(symbols=mol_data["symbols"], coordinates=coords)


def run_adaptive_command(args: argparse.Namespace):
    """Handles the 'run-adaptive' subcommand."""
    print(f"Loading adaptive workflow config: {args.config_file}")
    try:
        config = load_config(args.config_file)
    except FileNotFoundError:
        print(f"Error: Configuration file not found at {args.config_file}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error loading or parsing configuration file: {e}", file=sys.stderr)
        sys.exit(1)

    # Extract options
    adaptive_options = config.get("adaptive", {})
    backend_config = config.get("backend", {})
    backend_name = backend_config.get("name", "psi4") # Default to psi4
    backend_options = backend_config.get("options", {})

    print(f"Using backend: {backend_name}")

    # Parse tasks (expecting one for adaptive mode currently)
    config_tasks = config.get("tasks", [])
    if not config_tasks:
        print("Error: No 'tasks' defined in the configuration file.", file=sys.stderr)
        sys.exit(1)
    if len(config_tasks) > 1:
        print("Warning: Multiple tasks found in config. Adaptive mode currently uses only the first task.", file=sys.stderr)

    task_config = config_tasks[0]
    task_id = task_config.get("task_id", "adaptive_task_1") # Default task ID
    dimer_config = task_config.get("dimer", {})

    try:
        monomer_a = _create_molecule(dimer_config.get("monomer_a", {}))
        monomer_b = _create_molecule(dimer_config.get("monomer_b", {}))
    except ValueError as e:
        print(f"Error creating molecules from config: {e}", file=sys.stderr)
        sys.exit(1)

    # Create the SaptTask object
    sapt_task = SaptTask(
        id=task_id,
        # Combine monomers into a Dimer object - Assuming SaptTask takes monomers
        monomer_a=monomer_a,
        monomer_b=monomer_b,
        basis=task_config.get("basis"), # Can be None, workflow handles default
        method=task_config.get("method", "sapt0"), # Default method
        psi4_keywords=task_config.get("psi4_keywords", {})
    )

    print(f"Prepared task '{sapt_task.id}' for adaptive workflow.")

    # Call the adaptive workflow runner
    try:
        adaptive_results = run_adaptive_workflow(
            tasks=[sapt_task], # Pass as a list
            backend_name=backend_name,
            backend_options=backend_options,
            adaptive_options=adaptive_options,
            max_workers=args.max_workers
        )
    except Exception as e:
         print(f"\nError during adaptive workflow execution: {e}", file=sys.stderr)
         # Potentially print more traceback info here if needed
         sys.exit(1)

    # Print results
    print("\n--- Adaptive Workflow Results ---")
    if not adaptive_results:
        print("No results returned from the workflow.")
    else:
        # Result dict keys are task IDs or task_id_rungX if it failed early
        for result_key, result in adaptive_results.items():
            print(f"\nResult for '{result_key}':")
            if result.success:
                 print("  Status: Success")
                 # Print final basis, rung, convergence status if available
                 final_basis = result.metadata.get('converged_basis', 'N/A')
                 final_rung = result.metadata.get('final_rung', 'N/A')
                 converged = result.metadata.get('convergence_achieved', 'N/A')
                 print(f"  Final Basis: {final_basis} (Rung {final_rung})")
                 print(f"  Convergence Achieved: {converged}")
                 print("  Energies (kcal/mol):")
                 # Pretty print energies dict
                 energies_str = json.dumps(result.energies, indent=4)
                 print(energies_str)
            else:
                 print("  Status: Failed")
                 print(f"  Error: {result.error_message}")

    print("\nAdaptive workflow execution finished.")


def main(argv: Optional[List[str]] = None):
    """
    Main entry point for the SAPTASE CLI.

    Args:
        argv: Optional list of arguments (uses sys.argv if None).
    """
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        description="SAPTASE: Automated Multi-Fidelity SAPT(DFT) Workflows."
    )
    subparsers = parser.add_subparsers(
        title="Commands", dest="command", required=True, help="Available commands"
    )

    # --- run-adaptive command ---
    parser_adaptive = subparsers.add_parser(
        "run-adaptive", help="Run an adaptive basis set escalation workflow."
    )
    parser_adaptive.add_argument(
        "config_file", type=str, help="Path to the YAML configuration file."
    )
    parser_adaptive.add_argument(
        "-w",
        "--max-workers",
        type=int,
        default=None,
        help="Maximum number of parallel workers (defaults to system CPU count).",
    )
    parser_adaptive.set_defaults(func=run_adaptive_command)

    # --- Add other commands here later (e.g., 'run' for standard workflow) ---

    if not argv:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

# saptase/cli.py
"""
Command-line interface for the SAPTASE workflow manager.
"""

import argparse
import json
import logging
import os  # For cpu_count
import sys
from typing import Any, Dict, List, Optional

import numpy as np  # Needed for Molecule coordinates

from .config import EXECUTION  # Global scratch config
from .core.interop.yaml import load_config  # YAML loader
from .core.models import Molecule, SaptTask
from .core.orchestrator import SaptWorkflow, run_adaptive_workflow  # Add SaptWorkflow

logger = logging.getLogger(__name__)  # Use module-level logger


def _create_molecule(mol_data: dict) -> Molecule:
    """Helper to create a Molecule object from config data."""
    # Handle different input formats (string or dict)
    if isinstance(mol_data, str):
        # Assume it's an XYZ string block
        return Molecule.from_xyz_string(mol_data)
    elif isinstance(mol_data, dict):
        # Handle dict-based definition (original logic or file path)
        if "xyz" in mol_data:  # XYZ string within dict
            return Molecule.from_xyz_string(
                mol_data["xyz"],
                charge=mol_data.get("charge", 0),
                multiplicity=mol_data.get("multiplicity", 1),
            )
        elif "file" in mol_data:  # Path to XYZ file
            return Molecule.from_xyz_file(
                mol_data["file"],
                charge=mol_data.get("charge", 0),
                multiplicity=mol_data.get("multiplicity", 1),
            )
        elif "symbols" in mol_data and "coordinates" in mol_data:  # Explicit symbols/coords
            # Convert coordinates to numpy array
            coords = np.array(mol_data["coordinates"], dtype=float)
            if coords.ndim != 2 or coords.shape[1] != 3:
                raise ValueError(
                    f"Coordinates must be a list of [x, y, z] lists/tuples. Got shape {coords.shape}"
                )
            return Molecule(
                symbols=mol_data["symbols"],
                coordinates=coords,
                charge=mol_data.get("charge", 0),
                multiplicity=mol_data.get("multiplicity", 1),
                name=mol_data.get("name"),
            )
        else:
            raise ValueError("Molecule definition needs 'xyz', 'file', or 'symbols'/'coordinates'.")
    else:
        raise TypeError(f"Unexpected type for molecule data: {type(mol_data)}")


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
    execution_config = config.get("execution", {})
    # CLI workers override YAML workers only if CLI workers is provided
    cli_workers = args.workers
    yaml_workers = execution_config.get(
        "workers", execution_config.get("dask", {}).get("n_workers")
    )
    workers = cli_workers if cli_workers is not None else yaml_workers

    backend_config = config.get("backend", {})
    backend_name = backend_config.get("name", "psi4")  # Default to psi4
    backend_options = backend_config.get("options", {})

    print(f"Using backend: {backend_name}")

    # Parse tasks (expecting one for adaptive mode currently)
    config_tasks = config.get("tasks", [])
    if not config_tasks:
        print("Error: No 'tasks' defined in the configuration file.", file=sys.stderr)
        sys.exit(1)
    if len(config_tasks) > 1:
        print(
            "Warning: Multiple tasks found in config. "
            "Adaptive mode currently uses only the first task.",
            file=sys.stderr,
        )

    task_config = config_tasks[0]
    task_id = task_config.get("id", "adaptive_task_1")  # Default task ID if not present

    try:
        # Updated to handle new _create_molecule logic
        monomer_a_data = task_config.get("monomer_a", {})
        monomer_b_data = task_config.get("monomer_b", {})
        if not monomer_a_data or not monomer_b_data:
            raise ValueError("Both 'monomer_a' and 'monomer_b' must be defined in the task.")
        monomer_a = _create_molecule(monomer_a_data)
        monomer_b = _create_molecule(monomer_b_data)
    except (ValueError, TypeError) as e:
        print(f"Error creating molecules from config for task '{task_id}': {e}", file=sys.stderr)
        sys.exit(1)

    # Create the SaptTask object
    sapt_task = SaptTask(
        id=task_id,
        monomer_a=monomer_a,
        monomer_b=monomer_b,
        basis_set=task_config.get("basis_set", "jun-cc-pVDZ"),  # Match model field name
        method=task_config.get("method", "sapt0"),  # Default method
        additional_keywords=task_config.get("additional_keywords", {}),  # Match model field name
    )

    print(f"Prepared task '{sapt_task.id}' for adaptive workflow.")

    # Call the adaptive workflow runner
    try:
        adaptive_results = run_adaptive_workflow(
            tasks=[sapt_task],  # Pass as a list
            backend_name=backend_name,
            backend_options=backend_options,
            adaptive_options=adaptive_options,
            max_workers=workers,  # Use merged workers value
        )
    except Exception as e:
        print(f"\nError during adaptive workflow execution: {e}", file=sys.stderr)
        # Potentially print more traceback info here if needed
        sys.exit(1)

    # Print results (Simplified for brevity, original logic preserved conceptually)
    print("\n--- Adaptive Workflow Results ---")
    if not adaptive_results:
        print("No results returned from the workflow.")
    else:
        # Assume adaptive_results contains the final SaptResult keyed by original task ID
        final_result = adaptive_results.get(sapt_task.id)
        if final_result:
            print(f"\nResult for '{sapt_task.id}':")
            if final_result.success:
                print("  Status: Success")
                # Extract details if available in the result object itself
                final_basis = getattr(final_result, "basis_set", "N/A")
                # Rung info might need dedicated field in SaptResult or parsing logic
                # converged = getattr(final_result, 'convergence_achieved', 'N/A')
                print(f"  Final Basis: {final_basis}")
                # print(f"  Convergence Achieved: {converged}")
                print("  Energies:")
                energies_str = json.dumps(final_result.energies, indent=4)
                print(energies_str)
            else:
                print("  Status: Failed")
                error_msg = getattr(final_result, "error_message", "Unknown error")
                print(f"  Error: {error_msg}")
        else:
            print(f"Result for task ID '{sapt_task.id}' not found in output.")

    print("\nAdaptive workflow execution finished.")


def run_command(args: argparse.Namespace):
    """Handles the 'run' subcommand for standard workflows."""
    logger.info(f"Loading standard workflow config: {args.job_file}")
    try:
        config = load_config(args.job_file)
    except FileNotFoundError:
        logger.error(f"Configuration file not found at {args.job_file}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error loading or parsing configuration file: {e}")
        sys.exit(1)

    # --- Configuration Merging ---
    execution_config = config.get("execution", {})

    # Mode: CLI > YAML > default ('auto')
    mode = args.mode or execution_config.get("mode", "auto")

    # Workers: CLI > YAML (execution.workers or execution.dask.n_workers) > default (None)
    cli_workers = args.workers
    yaml_workers = execution_config.get(
        "workers", execution_config.get("dask", {}).get("n_workers")
    )
    workers = cli_workers if cli_workers is not None else yaml_workers
    if workers is None and mode in ["local_parallel", "dask"]:
        workers = os.cpu_count()
        logger.debug(f"Defaulting workers to CPU count: {workers}")
    elif workers is not None:
        try:
            workers = int(workers)
        except ValueError:
            logger.error(f"Invalid value for workers: '{workers}'. Must be an integer.")
            sys.exit(1)

    # Scheduler: CLI > YAML > None)
    scheduler = (
        args.scheduler
        if args.scheduler is not None
        else execution_config.get(
            "scheduler",
            execution_config.get("dask", {}).get("scheduler"),
        )
    )

    # Scratch Root: CLI > YAML > Default (from config.EXECUTION)
    scratch_root_cli = args.scratch_root  # Read from args now
    scratch_root_yaml = execution_config.get("scratch_root")
    scratch_root_default = EXECUTION.scratch_root
    # Precedence: CLI > YAML > Default
    scratch_root = scratch_root_cli if scratch_root_cli is not None else scratch_root_yaml
    if scratch_root is None:
        scratch_root = scratch_root_default
    logger.debug(f"Using scratch root: {scratch_root}")

    # Keep Scratch: CLI > YAML > Default (from config.EXECUTION)
    keep_scratch_cli = args.keep_scratch  # Read from args now
    keep_scratch_yaml = execution_config.get("keep_scratch")
    keep_scratch_default = EXECUTION.keep_scratch
    # Precedence: CLI flag present > YAML > Default
    # Note: args.keep_scratch is True if flag present, False if not, None if not defined (shouldn't happen with action='store_true')
    if keep_scratch_cli:  # If CLI flag --keep-scratch is used, it overrides everything
        keep_scratch = True
    elif keep_scratch_yaml is not None:
        keep_scratch = bool(keep_scratch_yaml)
    else:
        keep_scratch = keep_scratch_default
    logger.debug(f"Keep scratch directories: {keep_scratch}")

    # --- Workflow Construction ---
    workflow = SaptWorkflow()  # Uses default backend (Psi4)

    config_tasks = config.get("tasks", [])
    if not config_tasks:
        logger.error("No 'tasks' defined in the configuration file.")
        sys.exit(1)

    logger.info(f"Found {len(config_tasks)} tasks in configuration.")

    tasks_to_run: List[SaptTask] = []
    for i, task_config in enumerate(config_tasks):
        task_id = task_config.get("id", f"task_{i+1}")
        try:
            monomer_a = _create_molecule(task_config.get("monomer_a", {}))
            monomer_b = _create_molecule(task_config.get("monomer_b", {}))

            task = SaptTask(
                id=task_id,
                monomer_a=monomer_a,
                monomer_b=monomer_b,
                basis_set=task_config.get("basis_set", "jun-cc-pVDZ"),
                method=task_config.get("method", "sapt0"),
                additional_keywords=task_config.get("additional_keywords", {}),
            )

            # IMPORTANT: Add CLI scratch settings to task keywords BEFORE adding to workflow
            # This ensures they override YAML/defaults handled by add_task
            if scratch_root is not None:
                task.additional_keywords["scratch_root"] = scratch_root
            # keep_scratch needs care - add_task defaults to False if not present
            # We only need to set it if the final decision was True
            if keep_scratch:
                task.additional_keywords["keep_scratch"] = True

            workflow.add_task(task)
            tasks_to_run.append(task)  # Keep track for reporting if needed

        except (ValueError, TypeError) as e:
            logger.error(f"Error processing task '{task_id}' from config: {e}")
            sys.exit(1)

    # --- Execute Workflow ---
    logger.info(f"Executing workflow with mode: {mode}")
    results: Optional[Dict[str, SaptResult]] = None
    try:
        if mode == "local_serial":
            results = workflow.run_local_serial()
        elif mode == "local_parallel":
            results = workflow.run_local_parallel(max_workers=workers)
        elif mode == "dask":
            results = workflow.run_dask(max_workers=workers, scheduler=scheduler)
        elif mode == "auto":
            # Simple auto logic: use parallel if multiple tasks, else serial
            if len(tasks_to_run) > 1:
                logger.info("Auto mode: Using local_parallel for multiple tasks.")
                results = workflow.run_local_parallel(max_workers=workers)
            else:
                logger.info("Auto mode: Using local_serial for single task.")
                results = workflow.run_local_serial()
        else:
            logger.error(f"Unsupported execution mode: {mode}")
            sys.exit(1)

    except Exception as e:
        logger.critical(f"Workflow execution failed: {e}", exc_info=True)
        sys.exit(1)

    # --- Report Results --- (Optional: Basic summary)
    if results:
        success_count = sum(1 for r in results.values() if r.success)
        fail_count = len(results) - success_count
        logger.info(
            f"Workflow finished. Tasks completed: {success_count}, Tasks failed: {fail_count}"
        )
        # Add more detailed reporting if needed
    else:
        logger.warning("Workflow execution did not return results.")


def main(argv: Optional[List[str]] = None):
    """
    Main entry point for the SAPTASE CLI.

    Args:
        argv: Optional list of arguments (uses sys.argv if None).
    """
    # Setup basic logging for the CLI
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        description="SAPTASE: Automated Multi-Fidelity SAPT(DFT) Workflows.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,  # Show defaults in help
    )
    subparsers = parser.add_subparsers(
        title="Commands", dest="command", required=True, help="Available commands"
    )

    # --- run-adaptive command ---
    parser_adaptive = subparsers.add_parser(
        "run-adaptive",
        help="Run an adaptive basis set escalation workflow (legacy).",  # Mark as legacy?
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser_adaptive.add_argument(
        "config_file", type=str, help="Path to the YAML configuration file."
    )
    # Add arguments that were missing before to match run command if needed
    parser_adaptive.add_argument(
        "--mode",
        choices=["auto", "serial", "local_parallel", "dask"],
        default=None,  # Default handled inside command
        help="Override execution mode specified in YAML file.",
    )
    parser_adaptive.add_argument(
        "-w",
        "--workers",
        type=int,
        default=None,
        help="Max workers (local) or workers/node (Dask LocalCluster). Overrides YAML.",
    )
    parser_adaptive.add_argument(
        "--scheduler",
        type=str,
        default=None,
        help="Dask scheduler address (e.g., tcp://...). Overrides YAML.",
    )
    parser_adaptive.add_argument(
        "--scratch-root",
        type=str,
        default=None,
        help="Root directory for scratch files (overrides config).",
    )
    parser_adaptive.add_argument(
        "--keep-scratch",
        action="store_true",
        help="Keep scratch directories (overrides config).",
    )
    parser_adaptive.set_defaults(func=run_adaptive_command)

    # --- run command (New) ---
    parser_run = subparsers.add_parser(
        "run",
        help="Run a standard SAPT workflow from a configuration file.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser_run.add_argument(
        "job_file", type=str, help="Path to the YAML/JSON job configuration file."
    )
    parser_run.add_argument(
        "--mode",
        choices=["auto", "serial", "local_parallel", "dask"],
        default=None,  # Default handled inside command
        help="Override execution mode specified in YAML file.",
    )
    parser_run.add_argument(
        "-w",
        "--workers",
        type=int,
        default=None,
        help="Max workers (local) or workers/node (Dask LocalCluster). Overrides YAML.",
    )
    parser_run.add_argument(
        "--scheduler",
        type=str,
        default=None,
        help="Dask scheduler address (e.g., tcp://...). Overrides YAML.",
    )
    parser_run.add_argument(
        "--scratch-root",
        type=str,
        default=None,
        help="Root directory for scratch files (overrides config file).",
    )
    parser_run.add_argument(
        "--keep-scratch",
        action="store_true",
        help="Keep scratch directories after calculations (overrides config file).",
    )
    parser_run.set_defaults(func=run_command)

    # ------------------------------------------------------------------
    # Global options applicable to all sub-commands
    # ------------------------------------------------------------------
    parser.add_argument(
        "--scratch-root",
        type=str,
        default=None,
        help="Override default scratch directory root (env SAPTASE_SCRATCH_ROOT).",
    )
    parser.add_argument(
        "--keep-scratch",
        action="store_true",
        help="Do **not** delete task scratch dirs after completion (debugging aid)",
    )

    if not argv:
        parser.print_help()
        sys.exit(1)

    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        # Catch argparse errors (like missing command) and exit gracefully
        # Argparse already prints the error message.
        sys.exit(e.code)  # Propagate the exit code from argparse

    # ------------------------------------------------------------------
    # Apply global CLI flags -> runtime config singleton BEFORE calling func
    # ------------------------------------------------------------------
    if args.scratch_root is not None:
        EXECUTION.scratch_root = args.scratch_root
    if args.keep_scratch:
        EXECUTION.keep_scratch = True

    # Call the function associated with the chosen subcommand
    args.func(args)


if __name__ == "__main__":
    main()

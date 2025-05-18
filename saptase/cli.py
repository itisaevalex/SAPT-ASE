# saptase/cli.py
"""
Command-line interface for the SAPTASE workflow manager.
"""

import argparse
import json
import logging
import os  # For cpu_count
import sqlite3
import sys
from typing import Dict, List, Optional

import numpy as np  # Needed for Molecule coordinates

from .config import EXECUTION  # Global scratch config
from .core.errors import ConfigError, SaptError
from .core.interop.yaml import load_config  # YAML loader
from .core.logdb import LogDb  # Added import
from .core.models import Molecule, SaptResult, SaptTask
from .core.orchestrator import SaptWorkflow, run_adaptive_workflow  # Add SaptWorkflow

logger = logging.getLogger(__name__)  # Use module-level logger


def _get_db_path(args: argparse.Namespace, config: Optional[dict] = None) -> str:
    """Determine the database path from args or config."""
    if args.db_path:
        return args.db_path
    if config:
        provenance_config = config.get("provenance", {})
        if provenance_config.get("db_path"):
            return provenance_config["db_path"]
    # Fallback to a default if no other path is specified
    default_db_path = "runs/runs.sqlite"  # Or derive from a central config
    logger.warning(f"Database path not specified, defaulting to: {default_db_path}")
    return default_db_path


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
        # Attempt to run basis bootstrap early
        from saptase.hooks.basis_bootstrap import ensure_bases

        ensure_bases()
    except Exception as e:
        # Log and continue if bootstrap fails, as it's an enhancement
        logger.warning(f"Basis bootstrap failed: {e}. Proceeding without it.")

    try:
        config = load_config(args.config_file)
    except FileNotFoundError:
        print(f"Error: Configuration file not found at {args.config_file}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error loading or parsing configuration file: {e}", file=sys.stderr)
        sys.exit(1)

    # Determine db_path
    db_path = _get_db_path(args, config)
    logger.info(f"Using database path: {db_path}")

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
            db_path=db_path,  # Pass determined db_path
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
        # Attempt to run basis bootstrap early
        from saptase.hooks.basis_bootstrap import ensure_bases

        ensure_bases()
    except Exception as e:
        # Log and continue if bootstrap fails, as it's an enhancement
        logger.warning(f"Basis bootstrap failed: {e}. Proceeding without it.")

    try:
        config = load_config(args.job_file)
    except FileNotFoundError:
        logger.error(f"Configuration file not found at {args.job_file}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error loading or parsing configuration file: {e}")
        sys.exit(1)

    # Determine db_path (used by SaptWorkflow)
    db_path = _get_db_path(args, config)
    logger.info(f"Using database for workflow: {db_path}")

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
    # Read backend configuration from YAML, defaulting to psi4
    backend_name = execution_config.get("backend", "psi4")
    backend_options = execution_config.get("backend_options", {})

    logger.info(f"Using backend: {backend_name} with options: {backend_options}")
    try:
        from .core.backend import get_backend  # Ensure get_backend is imported

        selected_backend = get_backend(backend_name, options=backend_options)
        workflow = SaptWorkflow(backend=selected_backend, db_path=db_path)
        logger.info(f"Successfully initialized SaptWorkflow with backend: {backend_name}")
    except Exception as e:
        logger.error(
            f"Failed to initialize SaptWorkflow with backend '{backend_name}': {e}. "
            f"Falling back to default SaptWorkflow initialization."
        )
        workflow = SaptWorkflow(db_path=db_path)

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
        if mode == "serial":
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

        # ADDED: Detailed reporting for successful tasks
        logger.info("--- Detailed Task Results ---")
        for task_id, res_obj in results.items():
            if res_obj.success and hasattr(res_obj, "energies") and res_obj.energies:
                # Energies are typically in Hartrees from Psi4
                e_tot_hartree = sum(res_obj.energies.values())

                # Conversion factor from Hartree to kcal/mol
                HARTREE_TO_KCAL_MOL = 627.50960803
                e_tot_kcal_mol = e_tot_hartree * HARTREE_TO_KCAL_MOL

                energies_kcal_mol_str_parts = []
                for k, v_hartree in res_obj.energies.items():
                    v_kcal_mol = v_hartree * HARTREE_TO_KCAL_MOL
                    energies_kcal_mol_str_parts.append(f"{k}={v_kcal_mol:.4f}")
                energies_kcal_mol_display = ", ".join(energies_kcal_mol_str_parts)

                logger.info(f"  Task: {task_id}")
                logger.info("    Status: COMPLETED")
                logger.info(
                    f"    Total SAPT Interaction Energy: {e_tot_kcal_mol:.4f} kcal/mol ({e_tot_hartree:.8f} Ha)"
                )
                logger.info(f"    Components (kcal/mol): {energies_kcal_mol_display}")
                # Optionally log raw Hartree components if needed for extreme precision
                # logger.info(f"    Components (Ha): {res_obj.energies}")
            elif not res_obj.success:
                logger.info(f"  Task: {task_id}")
                logger.info("    Status: FAILED")
                logger.info(f"    Error: {getattr(res_obj, 'error_message', 'N/A')}")
                logger.info(f"    Error Code: {getattr(res_obj, 'error_code', 'N/A')}")
            else:  # Successful but no energies attribute or it's empty
                logger.info(f"  Task: {task_id}")
                logger.info(
                    "    Status: COMPLETED (energies attribute missing or empty in SaptResult object)"
                )

    else:
        logger.warning("Workflow execution did not return results.")

    print("\nStandard workflow execution finished.")


def results_command(args: argparse.Namespace):
    """Handles the 'results' subcommand to fetch and display run results."""
    # Load config to find db_path if not provided directly
    config = None
    if args.job_file:  # Optional job file for results command
        try:
            config = load_config(args.job_file)
        except Exception as e:
            logger.warning(f"Could not load job config {args.job_file} to infer db_path: {e}")

    db_path = _get_db_path(args, config)
    logger.info(f"Fetching results for run_id '{args.run_id}' from database: {db_path}")

    logdb = LogDb(db_path)
    try:
        fetched_results = logdb.fetch_results(args.run_id)
        if fetched_results:
            print(f"Results for run_id '{args.run_id}':")
            print(json.dumps(fetched_results, indent=4))
        else:
            print(f"No results found for run_id '{args.run_id}'.")
    finally:
        logdb.close()


def db_deduplicate_command(args: argparse.Namespace):
    """Handles the 'db deduplicate' subcommand."""
    # Config is not strictly needed for deduplication if db_path is direct
    db_path = _get_db_path(args)  # Pass args directly
    logger.info(f"Deduplicating tasks in database: {db_path}")
    logdb = LogDb(db_path)
    try:
        removed_ids = logdb.deduplicate_tasks(overwrite=args.overwrite)
        if removed_ids:
            print(f"Deduplication complete. Removed {len(removed_ids)} task log entries.")
            logger.info(f"Removed log_ids: {removed_ids}")
        else:
            print("No duplicate tasks found to remove.")
    finally:
        logdb.close()


def db_delete_failed_command(args: argparse.Namespace):
    """Handles the 'db delete-failed' subcommand."""
    db_path = _get_db_path(args)  # Pass args directly
    logger.info(f"Deleting failed tasks from database: {db_path}")
    logdb = LogDb(db_path)
    try:
        num_deleted = logdb.delete_failed_tasks()
        if num_deleted > 0:
            print(f"Successfully deleted {num_deleted} failed task(s) from the database.")
        else:
            print("No failed tasks found to delete.")
    finally:
        logdb.close()


def db_vacuum_command(args: argparse.Namespace):
    """Handles the 'db vacuum' subcommand."""
    db_path_to_vacuum = _get_db_path(args)
    logger.info(f"Attempting to VACUUM database: {db_path_to_vacuum}")
    try:
        # LogDb handles its own connection, so we pass the path
        logdb = LogDb(db_path_to_vacuum)
        success = logdb.vacuum_db()
        logdb.close()
        if success:
            print(f"Database {db_path_to_vacuum} VACUUMED successfully.")
        else:
            print(f"Failed to VACUUM database {db_path_to_vacuum}.")
    except Exception as e:
        print(f"Error during database VACUUM: {e}", file=sys.stderr)
        logger.error(f"Error during database VACUUM for {db_path_to_vacuum}: {e}", exc_info=True)


def db_merge_command(args: argparse.Namespace):
    """Handles the 'db merge' subcommand."""
    target_db_path = _get_db_path(args) # Target DB from --db-path or default
    source_db_path = args.source_db

    if not source_db_path:
        print("Error: --source-db argument is required for merge operation.", file=sys.stderr)
        sys.exit(1)

    logger.info(f"Attempting to merge database {source_db_path} into {target_db_path}")

    try:
        # Initialize LogDb with the target database
        target_logdb = LogDb(target_db_path)
        merge_stats = target_logdb.merge_from_db(source_db_path)
        target_logdb.close()

        print(f"Database merge completed.")
        print(f"  Source: {source_db_path}")
        print(f"  Target: {target_db_path}")
        print(f"  Task Logs Merged: {merge_stats['task_logs_merged']}")
        print(f"  Task Logs Skipped: {merge_stats['task_logs_skipped']}")
        print(f"  Results Merged: {merge_stats['results_merged']}")
        print(f"  Results Skipped: {merge_stats['results_skipped']}")

    except ConnectionError as e:
        print(f"Database connection error: {e}", file=sys.stderr)
        logger.error(f"Database connection error during merge: {e}", exc_info=True)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"Database file error: {e}", file=sys.stderr)
        logger.error(f"Database file error during merge: {e}", exc_info=True)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred during database merge: {e}", file=sys.stderr)
        logger.error(f"Unexpected error during database merge: {e}", exc_info=True)
        sys.exit(1)


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
    parser_run.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to the SQLite database file (e.g., runs/runs.sqlite). Overrides config file or default.",
    )
    parser_run.add_argument(
        "--max-workers-big-basis",
        type=int,
        default=None,
        help="Limit max workers for tasks identified as using a 'big basis' (e.g., QZ or 5Z). Default: use general workers limit. (Feature requires further integration in workflow logic)",
    )
    parser_run.set_defaults(func=run_command)

    # --- 'results' subcommand ---
    results_parser = subparsers.add_parser(
        "results", help="Fetch and display results from the database."
    )
    results_parser.add_argument("run_id", help="The run_id to fetch results for.")
    results_parser.add_argument(
        "--job-file",
        "-j",
        type=str,
        help="Optional: Path to the YAML job file (to infer db_path if not directly provided).",
    )
    results_parser.add_argument(
        "--db-path",
        type=str,
        default=None,  # Allow inferring from job_file or default
        help="Path to the SQLite database file (e.g., runs/runs.sqlite). Overrides job_file inference.",
    )
    results_parser.set_defaults(func=results_command)

    # --- 'db' subcommand group ---
    db_parser = subparsers.add_parser("db", help="Database management utilities (deduplicate, delete-failed, vacuum, merge)")
    db_subparsers = db_parser.add_subparsers(title="db_commands", dest="db_command")
    db_subparsers.required = True

    # Deduplicate command
    dedup_parser = db_subparsers.add_parser(
        "deduplicate", help="Deduplicate task entries in the database."
    )
    dedup_parser.add_argument(
        "--db-path", help="Path to the SQLite database file (overrides config)."
    )
    dedup_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing entries with the one having the latest timestamp if duplicates are found based on content hash.",
    )
    dedup_parser.set_defaults(func=db_deduplicate_command)

    # Delete-failed command
    delete_failed_parser = db_subparsers.add_parser(
        "delete-failed", help="Delete failed task entries from the database."
    )
    delete_failed_parser.add_argument(
        "--db-path", help="Path to the SQLite database file (overrides config)."
    )
    delete_failed_parser.set_defaults(func=db_delete_failed_command)

    # Vacuum command
    vacuum_parser = db_subparsers.add_parser(
        "vacuum", help="Vacuum the SQLite database to free up space."
    )
    vacuum_parser.add_argument(
        "--db-path", help="Path to the SQLite database file (overrides config)."
    )
    vacuum_parser.set_defaults(func=db_vacuum_command)

    # Merge command
    merge_parser = db_subparsers.add_parser(
        "merge", help="Merge entries from a source database into the target database."
    )
    merge_parser.add_argument(
        "--source-db",
        required=True,
        help="Path to the source SQLite database file to merge from."
    )
    merge_parser.add_argument(
        "--db-path", 
        help="Path to the target SQLite database file (defaults to runs/runs.sqlite or as in config)."
    )
    merge_parser.set_defaults(func=db_merge_command)

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
    if hasattr(args, "func"):
        try:
            args.func(args)
        except ConfigError as e:  # Catch custom config errors
            logger.error(
                f"Configuration Error: {e}", exc_info=args.debug
            )  # Show traceback if debug
            sys.exit(2)
        except SaptError as e:  # Catch custom saptase errors
            logger.error(f"SAPTASE Error: {e}", exc_info=args.debug)
            sys.exit(3)
        except sqlite3.Error as e:  # Catch SQLite errors
            logger.error(f"Database Error: {e}", exc_info=args.debug)
            sys.exit(4)
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}", exc_info=args.debug)
            sys.exit(1)
    else:
        # If no subcommand was provided, print help for the main parser
        # If a subcommand was provided but it has no func (e.g., 'db' itself), print its help
        if hasattr(args, "db_command") and args.db_command is None:  # User typed 'saptase db'
            db_parser.print_help()
        elif not any(vars(args).values()):  # No args at all
            parser.print_help()
        else:  # Fallback, should ideally be caught by argparse 'required=True' on subparsers
            parser.print_help()


if __name__ == "__main__":
    main()

"""SAPT workflow orchestrator.

This module contains the main workflow logic for SAPT calculations.
"""

# Imports for parallel execution
import concurrent.futures
import os
import logging
import time # For timing
import uuid # For run IDs
from pathlib import Path # Added Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import json

from tqdm import tqdm

from .backend import Psi4Backend, SaptBackend
from .models import Molecule, SaptResult, SaptTask, TaskStatus
from .errors import SaptError  # Import base SaptError
from ..recovery.escalate import EscalationContext # Import recovery context
from .logdb import LogDb # Import LogDb

logger = logging.getLogger(__name__)


class MockBackend(SaptBackend):
    """Mock backend for testing without Psi4."""

    def calculate(self, task: SaptTask) -> SaptResult:
        """Mock calculation that returns a dummy result.

        Args:
            task: The SAPT calculation task to perform

        Returns:
            A dummy SaptResult
        """
        # Create a dummy result
        result = SaptResult(task_id=task.id)
        result.success = True
        result.energies = {
            "total": -0.007525,  # Approx water dimer energy
            "electrostatics": -0.012345,
            "exchange": 0.007890,
            "induction": -0.001234,
            "dispersion": -0.001836,
        }
        task.status = TaskStatus.COMPLETED
        return result


def get_default_backend() -> SaptBackend:
    """Get the default backend based on available packages.

    Returns:
        A SaptBackend instance (Psi4Backend if Psi4 is available, otherwise MockBackend)
    """
    try:
        return Psi4Backend()
    except ImportError:
        return MockBackend()


# Helper function for parallel execution (must be top-level for pickling)
def _execute_task_for_parallel(backend: SaptBackend, task: SaptTask, db_path: Path, run_id: str, max_attempts: int = 3) -> SaptResult:
    """Worker function to run a single task, handling retries.

    Args:
        backend: The backend to use.
        task: The task to execute.
        db_path: Path to the SQLite database file.
        run_id: The ID of the current run.
        max_attempts: Maximum number of recovery attempts.

    Returns:
        The final SaptResult (success or failure).

    Raises:
        RuntimeError: If recovery fails after max attempts.
    """
    # Ensure Psi4 uses only one thread per worker if applicable
    if isinstance(backend, Psi4Backend):
        os.environ["OMP_NUM_THREADS"] = "1"

    task.status = TaskStatus.RUNNING
    logger.info(f"Starting task {task.id}...")
    start_time = time.monotonic()
    context = EscalationContext(task=task, max_attempts=max_attempts)

    while True:
        try:
            logger.debug(f"Attempt {context.attempt_count + 1} for task {task.id} with basis {task.basis_set} and keywords {task.additional_keywords}")
            logger.info(f"Task {task.id}: Attempt {context.attempt_count + 1} with basis='{task.basis_set}' method='{task.method}'")
            result = backend.calculate(task)
            result.elapsed_time = time.monotonic() - start_time
            result.attempt_number = context.attempt_count # Store final attempt number
            result.task_id = task.id # Ensure result ID matches the (potentially retried) task ID
            # We don't need to explicitly set basis/method here if the backend does it
            # Explicitly set basis/method from the task object before returning
            result.basis_set = task.basis_set
            result.method = task.method
            
            # Diagnostic log: Show result state *before* returning from worker
            logger.info(f"WORKER_RETURN: result.task_id='{result.task_id}', result.basis_set='{getattr(result, 'basis_set', 'MISSING')}', result.method='{getattr(result, 'method', 'MISSING')}'")
            task.status = TaskStatus.COMPLETED
            logger.info(f"Task {task.id} completed successfully in {result.elapsed_time:.2f}s on attempt {context.attempt_count + 1}.")
            return result # Success!

        except SaptError as err:
            logger.warning(f"Task {task.id} failed on attempt {context.attempt_count + 1} with error: {err}")
            elapsed_time = time.monotonic() - start_time # Calculate elapsed time for this attempt
            try:
                # Store the error in context and check if we can retry
                if context.can_retry(err):
                    # --- Log the failed attempt BEFORE retrying ---
                    fail_result = SaptResult(
                        task_id=task.id,
                        success=False,
                        error_message=str(err)
                    )
                    fail_result.elapsed_time = elapsed_time
                    fail_result.attempt_number = context.attempt_count
                    fail_result.error_code = type(err).__name__
                    fail_result.error_details = json.dumps(context.history + [{'attempt': context.attempt_count, 'error': str(err), 'strategy': 'initial_failure'}]) # Store as JSON string
                    fail_result.basis_set = task.basis_set
                    fail_result.method = task.method

                    # --- Log the intermediate failure --- 
                    logger.info(f"Task {task.id}: Logging failed attempt {context.attempt_count + 1}...")
                    # Create a temporary LogDb instance for this process
                    temp_log_db = None
                    try:
                        temp_log_db = LogDb(db_path)
                        temp_log_db.log_task_result(
                            run_id=run_id,
                            result=fail_result,
                            basis_set=fail_result.basis_set, # Pass the task's basis
                            method=fail_result.method,     # Pass the task's method
                            elapsed_time=fail_result.elapsed_time,
                            error_code=fail_result.error_code,
                            error_details=fail_result.error_details,
                        )
                    except Exception as log_err:
                        logger.error(f"Task {task.id}: Failed to log failed attempt {context.attempt_count + 1} to database: {log_err}")
                    finally:
                        if temp_log_db:
                            temp_log_db.close() # Ensure connection is closed
                    # Apply the strategy (which uses the stored error)
                    recovered_task = context.apply()
                    # Update the task for the next loop iteration
                    if recovered_task: 
                        logger.info(f"Task {recovered_task.id}: Applied recovery strategy for {type(err).__name__}. Retrying as task {recovered_task.id}...")
                        task = recovered_task # Update task for the next iteration
                        task.status = TaskStatus.PENDING # Reset status for retry
                        continue # Go to next iteration of the while loop
                    else:
                        # This path should now be unreachable if can_retry works correctly
                        # The RuntimeError will be raised by can_retry or apply if max attempts reached
                        logger.error(f"Task {task.id}: Internal logic error - can_retry returned False but no exception was raised.")
                        raise RuntimeError(f"Task {task.id}: Cannot retry further, max attempts reached.")

            except RuntimeError as final_err: # Catch RuntimeError from context.apply()
                logger.error(f"Task {task.id} failed permanently after {context.attempt_count} attempts.")
                elapsed_time = time.monotonic() - start_time
                # Create a failure result containing history
                fail_result = SaptResult(
                    task_id=task.id,
                    success=False,
                    error_message=str(final_err) # Error from RuntimeError
                )
                fail_result.elapsed_time = elapsed_time
                fail_result.attempt_number = context.attempt_count
                fail_result.error_code = type(final_err).__name__ # RuntimeError
                # Ensure history is serializable (using strategy names)
                fail_result.error_details = json.dumps(context.history)
                fail_result.basis_set = task.basis_set
                fail_result.method = task.method
                task.status = TaskStatus.FAILED
                # We return the result here; run_local_parallel will handle logging it.
                return fail_result

        except Exception as base_exc: # Catch unexpected errors
            logger.error(f"Task {task.id} encountered unexpected error: {base_exc}", exc_info=True)
            elapsed_time = time.monotonic() - start_time
            # Create result with valid constructor args
            fail_result = SaptResult(
                task_id=task.id,
                success=False,
                error_message=str(base_exc)
            )
            # Set additional attributes
            fail_result.elapsed_time = elapsed_time
            fail_result.attempt_number = context.attempt_count + 1
            fail_result.error_code = type(base_exc).__name__
            # Ensure history is serializable (using strategy names already implemented)
            fail_result.error_details = json.dumps(context.history + [{'attempt': context.attempt_count + 1, 'error': str(base_exc)}]) # Store as JSON string
            fail_result.basis_set = task.basis_set
            fail_result.method = task.method
            task.status = TaskStatus.FAILED
            return fail_result


@dataclass
class SaptWorkflow:
    """Workflow for running SAPT calculations.

    This class manages multiple SAPT tasks and executes them using the provided backend.

    Attributes:
        backend: The backend to use for SAPT calculations
        tasks: List of SAPT tasks to run
        results: Dictionary mapping task IDs to results
        db_path: Path to the SQLite database file for provenance logging.
        logdb: Instance of the LogDb for database interactions.
    """

    backend: SaptBackend = field(default_factory=get_default_backend)
    tasks: List[SaptTask] = field(default_factory=list)
    results: Dict[str, SaptResult] = field(default_factory=dict)
    db_path: Path = field(default=Path("runs/runs.sqlite")) # Add db_path field
    logdb: LogDb = field(init=False) # Add logdb field, not initialized directly
    current_run_id: str = field(init=False) # Add current_run_id field

    def __post_init__(self):
        """Initialize LogDb after the main init."""
        self.logdb = LogDb(self.db_path) # Initialize LogDb here

    def add_task(self, task: SaptTask) -> None:
        """Add a SAPT task to the workflow.

        Args:
            task: The SAPT task to add
        """
        self.tasks.append(task)

    def add_dimer(
        self,
        monomer_a: Molecule,
        monomer_b: Molecule,
        basis_set: str = "jun-cc-pVDZ",
        method: str = "sapt0",
        task_id: Optional[str] = None,
        **kwargs,
    ) -> SaptTask:
        """Create and add a SAPT task for a dimer.

        Args:
            monomer_a: First monomer molecule
            monomer_b: Second monomer molecule
            basis_set: Basis set for the calculation
            method: SAPT method to use
            task_id: Optional task identifier
            **kwargs: Additional keywords for the backend

        Returns:
            The created SaptTask instance
        """
        task = SaptTask(
            monomer_a=monomer_a,
            monomer_b=monomer_b,
            basis_set=basis_set,
            method=method,
            id=task_id,
            additional_keywords=kwargs,
        )
        self.add_task(task)
        return task

    def run_local_serial(self) -> Dict[str, SaptResult]:
        """Run all tasks sequentially on the local machine.

        Returns:
            Dictionary mapping task IDs to results
        """
        for task in self.tasks:
            # Skip tasks that have already run
            if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                continue

            # Run the task and store the result
            result = self.backend.calculate(task)
            self.results[task.id] = result

        return self.results

    def run_local_parallel(self, max_workers: Optional[int] = None) -> Dict[str, SaptResult]:
        """Run all pending tasks in parallel on the local machine.

        Also logs task provenance to the configured LogDb.

        Args:
            max_workers: Maximum number of worker processes. Defaults to os.cpu_count().

        Returns:
            Dictionary mapping task IDs to results
        """
        # Generate a unique ID for this workflow run if not already set (allows re-runs? TBD)
        if not hasattr(self, 'current_run_id') or not self.current_run_id:
             self.current_run_id = f"run_{uuid.uuid4().hex[:8]}"
        logger.info(f"Starting workflow run_id: {self.current_run_id}")

        # Filter tasks that need to be run
        pending_tasks = [task for task in self.tasks if task.status == TaskStatus.PENDING]

        if not pending_tasks:
            print("No pending tasks to run.")
            return self.results

        print(
            f"Running {len(pending_tasks)} SAPT tasks on {max_workers} workers..."
        )

        # Map original task ID to task object for logging details
        task_details = {task.id: task for task in self.tasks}

        # Execute tasks using ProcessPoolExecutor
        results_list = []
        with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Map future to original task ID
            future_to_task_id = {
                executor.submit(_execute_task_for_parallel, self.backend, task, self.logdb.db_path, self.current_run_id): task.id
                for task in pending_tasks
            }

            # Process completed futures as they finish
            for future in tqdm(
                concurrent.futures.as_completed(future_to_task_id), total=len(pending_tasks)
            ):
                original_task_id = future_to_task_id[future]
                original_task = task_details.get(original_task_id) # Get original task details

                try:
                    result: SaptResult = future.result() # Result includes success/failure and details
                    self.results[original_task_id] = result # Store result using original ID
                    results_list.append(result)

                    # Update the status of the original task object in memory
                    if original_task:
                        original_task.status = TaskStatus.COMPLETED if result.success else TaskStatus.FAILED

                    if result.success:
                        # Diagnostic log: Show basis set seen by main process before logging
                        logger.info(f"MAIN_PROCESS_LOGGING: result.task_id='{result.task_id}', result.basis_set='{result.basis_set}', result.method='{result.method}'")
                        logger.info(f"Task {result.task_id} completed successfully in {result.elapsed_time:.2f}s on attempt {result.attempt_number + 1}.")
                        # Log the final *successful* result using details from the result object
                        self.logdb.log_task_result(
                            run_id=self.current_run_id,
                            result=result,
                            basis_set=result.basis_set, # Use basis from the successful result
                            method=result.method,     # Use method from the successful result
                            elapsed_time=result.elapsed_time, # Get from result object
                            error_code=getattr(result, 'error_code', None), # Get code if present
                            error_details=getattr(result, 'error_details', None) # Get details if present
                        )
                    else:
                        # Log the final *failed* result
                        # For failures, using original task basis/method might be okay, but using result's if available is safer
                        self.logdb.log_task_result(
                            run_id=self.current_run_id,
                            result=result,
                            basis_set=result.basis_set or original_task.basis_set, # Use result's basis if available, else original
                            method=result.method or original_task.method, # Use result's method if available, else original
                            elapsed_time=result.elapsed_time, # Get from result object
                            error_code=getattr(result, 'error_code', None), # Get code if present
                            error_details=getattr(result, 'error_details', None) # Get details if present
                        )

                except Exception as exc: # Catch rare errors during future.result() retrieval
                    logger.critical(f"Future for task {original_task_id} raised unexpected exception during result retrieval: {exc}", exc_info=True)
                    # Create and log a generic failure result for this specific error
                    fail_result = SaptResult(
                        task_id=original_task_id,
                        success=False,
                        error_message=f"Exception during future.result(): {exc}",
                        energies=None, # No energies calculated
                        raw_output=f"Error during result retrieval: {exc}"
                    )
                    fail_result.elapsed_time = -1.0 # Indicate unknown task time
                    fail_result.attempt_number = -1 # Indicate error retrieving attempt info
                    fail_result.error_code = "FutureRetrievalException"
                    fail_result.error_details = json.dumps([{'error': f"Exception during future.result(): {exc}"}]) # Store as JSON string
                    self.results[original_task_id] = fail_result
                    results_list.append(fail_result)

                    if original_task:
                        original_task.status = TaskStatus.FAILED
                        # Log this specific failure
                        self.logdb.log_task_result(
                            run_id=self.current_run_id,
                            result=fail_result,
                            basis_set=original_task.basis_set,
                            method=original_task.method,
                            elapsed_time=fail_result.elapsed_time,
                            error_code=fail_result.error_code,
                            error_details=fail_result.error_details
                        )

        self.logdb.close()

        logger.info(f"Parallel execution for run_id {self.current_run_id} finished. Processed {len(results_list)} tasks.")
        return self.results

    def get_result(self, task_id: str) -> Optional[SaptResult]:
        """Get the result for a specific task.

        Args:
            task_id: The ID of the task

        Returns:
            The result for the task, or None if not available
        """
        return self.results.get(task_id)


def run_sapt(
    monomer_a: Molecule,
    monomer_b: Molecule,
    basis_set: str = "jun-cc-pVDZ",
    method: str = "sapt0",
    backend: Optional[SaptBackend] = None,
    **kwargs,
) -> SaptResult:
    """Convenience function to run a single SAPT calculation.

    Args:
        monomer_a: First monomer molecule
        monomer_b: Second monomer molecule
        basis_set: Basis set for the calculation
        method: SAPT method to use
        backend: Backend to use for the calculation (defaults to get_default_backend())
        **kwargs: Additional keywords for the backend

    Returns:
        The result of the SAPT calculation
    """
    if backend is None:
        backend = get_default_backend()

    task = SaptTask(
        monomer_a=monomer_a,
        monomer_b=monomer_b,
        basis_set=basis_set,
        method=method,
        additional_keywords=kwargs,
    )
    result = backend.calculate(task)
    return result


# New convenience function for adaptive workflow
def run_adaptive_workflow(
    tasks: List[SaptTask],
    backend_name: str = "psi4",
    backend_options: Optional[Dict[str, Any]] = None,
    adaptive_options: Optional[Dict[str, Any]] = None,
    max_workers: Optional[int] = None,
) -> Dict[str, SaptResult]:
    """
    Convenience function to instantiate and run an AdaptiveWorkflow.

    Args:
        tasks: List of SaptTask objects (typically one for adaptive mode).
               The basis set in the task determines the starting point.
        backend_name: Name of the computational backend.
        backend_options: Options for the backend.
        adaptive_options: Options for the adaptive workflow (e.g., 'target_accuracy').
        max_workers: Maximum number of workers for parallel execution within rungs.

    Returns:
        Dictionary mapping the primary task ID to the final converged SaptResult,
        or all results if the run fails early.
    """
    from saptase.workflows.adaptive import AdaptiveWorkflow

    adaptive_workflow = AdaptiveWorkflow(
        tasks=tasks,
        backend_name=backend_name,
        backend_options=backend_options,
        adaptive_options=adaptive_options,
    )
    results = adaptive_workflow.run_adaptive(max_workers=max_workers)
    return results

"""SAPT workflow orchestrator.

This module contains the main workflow logic for SAPT calculations.
"""

# Imports for parallel execution
import concurrent.futures
import json
import logging
import os
import time  # For timing
import uuid  # For run IDs
from dataclasses import dataclass, field
from pathlib import Path  # Added Path
from typing import Any, Dict, List, Optional

from tqdm import tqdm

from ..recovery.escalate import EscalationContext  # Import recovery context
from .backend import Psi4Backend, SaptBackend
from .errors import SaptError  # Import base SaptError
from .logdb import LogDb  # Import LogDb
from .models import Molecule, SaptResult, SaptTask, TaskStatus

logger = logging.getLogger(__name__)


def get_default_backend() -> SaptBackend:
    """Always instantiate the production backend.

    Tests inject their own backend explicitly.

    Returns:
        A Psi4Backend instance
    """
    return Psi4Backend()


# Helper function for parallel execution (must be top-level for pickling)
def _configure_worker_logging():
    """Configures basic logging within the worker process."""
    # Configure root logger - adjust level and format as needed
    # Using force=True to ensure it applies even if basicConfig was called elsewhere
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)8s] %(process)d %(name)s:%(lineno)d: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


def _execute_task_for_parallel(
    backend: SaptBackend, task: SaptTask, db_path: Path, run_id: str, max_attempts: int = 3
) -> SaptResult:
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
    _configure_worker_logging()  # Configure logging for THIS process
    # Get a logger specific to this worker function after configuration
    worker_logger = logging.getLogger(__name__ + ".worker")

    # --- Initial Status Check ---
    # Check the *incoming* task status before starting execution.
    # Handle potential string conversion *before* this check as well
    if isinstance(task.status, str):
        try:
            status_value = task.status
            task.status = TaskStatus(status_value)
        except ValueError:
            worker_logger.error(
                f"Task {task.id}: Received invalid initial status string '{task.status}'. Failing task."
            )
            return SaptResult(
                task_id=task.id,
                success=False,
                error_message=f"Invalid initial status string '{task.status}' received by worker.",
                error_code="InvalidState",
            )

    if task.status not in [TaskStatus.PENDING, TaskStatus.RETRYING]:
        worker_logger.warning(
            f"Task {task.id} received with non-runnable status {task.status}. Skipping execution."
        )
        # Return a result reflecting this initial state
        return SaptResult(
            task_id=task.id,  # Use original task ID
            success=False,
            error_message=f"Task received by worker with non-runnable status: {task.status}",
            error_code="InvalidInitialState",
            attempt_number=0,  # No attempts made
        )

    # If status is PENDING or RETRYING, proceed.
    worker_logger.info(f"Starting task {task.id} (initial status: {task.status})...")
    # DO NOT set task.status = TaskStatus.RUNNING here

    # Ensure Psi4 uses only one thread per worker if applicable
    if isinstance(backend, Psi4Backend):
        os.environ["OMP_NUM_THREADS"] = "1"

    # Initialize local LogDb for logging each attempt in the worker process
    from .logdb import LogDb

    logdb = LogDb(db_path)

    context = EscalationContext(task=task, max_attempts=max_attempts)
    original_task_id = task.id  # Store original ID for final logging
    result = None  # Initialize result variable
    start_time = (
        time.monotonic()
    )  # Track start time for the first attempt (used if unexpected error)

    while True:
        # No need for string-to-Enum conversion as TaskStatus is now guaranteed to be an Enum

        # Log current status entering the loop
        worker_logger.debug(f"Task {task.id}: Entering loop. Status is now {task.status}")

        worker_logger.info(
            f"Task {task.id}: Attempt {context.attempt_index + 1} with basis='{task.basis_set}' method='{task.method}'"
        )
        current_attempt_start_time = time.monotonic()  # Time this specific attempt

        try:
            # --- Execute Calculation ---
            task_result = backend.calculate(
                task
            )  # Assume backend handles its own status logging if needed
            elapsed_time = time.monotonic() - current_attempt_start_time

            # --- Process Success ---
            if task_result.success:
                worker_logger.info(
                    f"Task {task.id} completed successfully on attempt {context.attempt_index + 1}."
                )
                # Use 0-based attempt numbering to be consistent with the recovery ladder
                task_result.attempt_number = context.attempt_index
                task_result.elapsed_time = elapsed_time
                task_result.basis_set = task.basis_set  # Ensure these are set from task state
                task_result.method = task.method

                # Log this successful attempt to the database
                logdb.log_task_attempt(run_id=run_id, result=task_result)

                result = task_result  # Store final success result
                break  # Exit the while loop on success

            # Should not happen if backend.calculate follows contract (raises SaptError on fail)
            else:
                worker_logger.error(
                    f"Task {task.id}: Backend returned non-success result without raising SaptError. Treating as failure."
                )
                # Synthesize an error to proceed with retry logic
                raise SaptError(
                    task_result.error_message or "Backend indicated failure without specific error"
                )

        except SaptError as err:
            worker_logger.warning(
                f"Task {task.id} failed on attempt {context.attempt_index + 1} with error: {err}"
            )
            elapsed_time = (
                time.monotonic() - current_attempt_start_time
            )  # Time for this failed attempt

            # Create a failed result with enough information for logging
            failed_attempt_result = SaptResult(
                task_id=task.id,
                success=False,
                error_message=str(err),
                error_code=type(err).__name__,
                basis_set=task.basis_set,
                method=task.method,
            )
            # Use consistent 0-based attempt numbering throughout the codebase
            failed_attempt_result.attempt_number = context.attempt_index
            failed_attempt_result.elapsed_time = elapsed_time

            # Log this failed attempt to the database
            logdb.log_task_attempt(run_id=run_id, result=failed_attempt_result)

            # Note: We don't need to call context.record_failure(err) separately anymore
            # since the refactored can_retry method now does this internally
            if context.can_retry(err):
                try:
                    retry_task = context.apply(
                        err
                    )  # Attempt to get the next task with the current error
                    worker_logger.info(
                        f"Task {retry_task.id}: Applied recovery strategy for {type(err).__name__}. Retrying as task {retry_task.id}..."
                    )
                    task = retry_task  # Update task for the next iteration
                    # task.status is already set to RETRYING by copy_with_retry in context.apply
                    continue  # Go to next iteration to execute the retry_task
                except RuntimeError as apply_err:  # Catch error if apply() fails
                    worker_logger.error(
                        f"Task {task.id}: Recovery attempt failed during apply(): {apply_err}. Failing permanently."
                    )
                    # Store info needed to create the final failure result below
                    final_err = apply_err
                    final_error_code = type(
                        err
                    ).__name__  # Use the SaptError that led to this point
            else:
                # If can_retry() is False, log it and prepare for final failure result
                worker_logger.warning(
                    f"Task {task.id}: No further recovery possible after attempt {context.attempt_index + 1}."
                )
                final_err = err  # Use the SaptError that triggered this failure
                final_error_code = type(err).__name__

            # --- If we reach here within the SaptError block, it means the task failed permanently ---
            # Construct failure result
            worker_logger.error(f"Task {original_task_id} failed permanently.")
            result = SaptResult(
                task_id=task.id,  # Use the current task ID (which is the retry ID for retry attempts)
                success=False,
                error_message=f"Task failed permanently after {context.attempt_index + 1} attempts. Last error: {type(final_err).__name__}: {final_err}",
                basis_set=task.basis_set,  # basis/method from the last failed attempt state
                method=task.method,
                attempt_number=context.attempt_index + 1,
                error_code=final_error_code,
                error_details=json.dumps(context.history),
            )
            result.elapsed_time = elapsed_time  # Use time from the last failed attempt
            break  # Exit the while loop as the task failed permanently

        except Exception as base_exc:  # Catch totally unexpected errors during calculation
            worker_logger.error(
                f"Task {task.id} encountered unexpected error during execution: {base_exc}",
                exc_info=True,
            )
            elapsed_time = time.monotonic() - current_attempt_start_time
            # Create a failure result for this unexpected error
            result = SaptResult(
                task_id=task.id,  # Use current task.id, not original_task_id
                success=False,
                error_message=f"Unexpected error during task execution: {type(base_exc).__name__}: {base_exc}",
                basis_set=task.basis_set,
                method=task.method,
                attempt_number=context.attempt_index + 1,
                error_code=type(base_exc).__name__,
                error_details=json.dumps([*context.history, {"error": f"Unexpected: {base_exc}"}]),
            )
            result.elapsed_time = elapsed_time
            break  # Exit loop on unexpected error

    # --- Final Logging (outside loop, within worker) ---
    # Ensure result is defined before logging
    if result is None:
        worker_logger.error(
            f"Internal error: _execute_task_for_parallel finished for task {original_task_id} without producing a result object."
        )
        # Create a generic failure result if something went drastically wrong
        result = SaptResult(
            task_id=task.id,  # Use current task.id, not original_task_id
            success=False,
            error_message="Internal orchestrator error: No result produced.",
            error_code="InternalOrchestratorError",
            attempt_number=context.attempt_index + 1,
        )
        # Try to capture elapsed time if possible
        if "start_time" in locals():
            result.elapsed_time = time.monotonic() - start_time

    # Log before returning, but DO NOT interact with DB from worker
    worker_logger.info(
        f"Task {original_task_id}: Worker finished. Returning result: Success={result.success}, ErrorCode={getattr(result, 'error_code', 'None')}"
    )
    worker_logger.debug(
        f"WORKER_LOGGING Task {task.id}: Returning result with attempt_number={getattr(result, 'attempt_number', 'None')}"
    )

    # Close the database connection before returning
    logdb.close()

    return result  # Return the final SaptResult


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
    db_path: Path = field(default=Path("runs/runs.sqlite"))  # Add db_path field
    logdb: LogDb = field(init=False)  # Add logdb field, not initialized directly
    current_run_id: str = field(init=False)  # Add current_run_id field

    def __post_init__(self):
        """Initialize LogDb after the main init."""
        self.logdb = LogDb(self.db_path)  # Initialize LogDb here

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
        if not hasattr(self, "current_run_id") or not self.current_run_id:
            self.current_run_id = f"run_{uuid.uuid4().hex[:8]}"
        logger.info(f"Starting workflow run_id: {self.current_run_id}")

        # Filter tasks that need to be run
        pending_tasks = [task for task in self.tasks if task.status == TaskStatus.PENDING]

        if not pending_tasks:
            print("No pending tasks to run.")
            return self.results

        print(f"Running {len(pending_tasks)} SAPT tasks on {max_workers} workers...")

        # Map original task ID to task object for logging details
        task_details = {task.id: task for task in self.tasks}

        # Execute tasks using ProcessPoolExecutor
        results_list = []
        with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Map future to original task ID
            future_to_task_id = {
                executor.submit(
                    _execute_task_for_parallel,
                    self.backend,
                    task,
                    self.logdb.db_path,
                    self.current_run_id,
                ): task.id
                for task in pending_tasks
            }

            # Process completed futures as they finish
            for future in tqdm(
                concurrent.futures.as_completed(future_to_task_id), total=len(pending_tasks)
            ):
                original_task_id = future_to_task_id[future]
                original_task = task_details.get(original_task_id)  # Get original task details

                try:
                    # Get the result from this specific future (one specific attempt)
                    result_from_future: SaptResult = future.result()

                    # Each attempt is already logged in the worker process
                    # We no longer need to log here in the main process

                    logger.debug(
                        f"Received result for task {result_from_future.task_id} (original: {original_task_id}), success={result_from_future.success}, attempt={getattr(result_from_future, 'attempt_number', 0)}"
                    )

                    # Determine if this result should become the final result using compact rules
                    existing = self.results.get(original_task_id)
                    replace = (
                        existing is None
                        or (result_from_future.success and not existing.success)
                        or (
                            not result_from_future.success
                            and not existing.success
                            and result_from_future.attempt_number > existing.attempt_number
                        )
                    )

                    # Log what happened
                    if existing is None:
                        logger.debug(
                            f"No previous result for {original_task_id}, using result from attempt {result_from_future.attempt_number}"
                        )
                    elif replace and result_from_future.success:
                        logger.debug(
                            f"Updated result for {original_task_id}: new success overrides previous failure"
                        )
                    elif replace and not result_from_future.success:
                        logger.debug(
                            f"Updated failed result for {original_task_id}: using attempt {result_from_future.attempt_number} instead of {existing.attempt_number}"
                        )
                    elif result_from_future.success and existing.success:
                        logger.debug(
                            f"Keeping existing success for {original_task_id} (attempt {existing.attempt_number}), ignoring later success from attempt {result_from_future.attempt_number}"
                        )

                    # Update the final result if needed
                    if replace:
                        # Store in results dictionary with original task ID as key
                        self.results[original_task_id] = result_from_future
                        results_list.append(result_from_future)

                        # Update the original task status based on the final result
                        if original_task:
                            original_task.status = (
                                TaskStatus.COMPLETED
                                if result_from_future.success
                                else TaskStatus.FAILED
                            )

                        # Log the state update
                        log_msg = f"Task {original_task_id}: final result updated to {result_from_future.task_id}, success={result_from_future.success}"
                        if hasattr(result_from_future, "attempt_number"):
                            log_msg += f" (attempt {result_from_future.attempt_number})"
                        logger.info(log_msg)

                except Exception as exc:  # Catch rare errors during future.result() retrieval
                    logger.critical(
                        f"Future for task {original_task_id} raised unexpected exception during result retrieval: {exc}",
                        exc_info=True,
                    )

                    # Create a generic failure result for this error
                    fail_result = SaptResult(
                        task_id=original_task_id,
                        success=False,
                        error_message=f"Exception during future.result(): {exc}",
                        energies=None,  # No energies calculated
                        raw_output=f"Error during result retrieval: {exc}",
                    )
                    fail_result.elapsed_time = -1.0  # Indicate unknown task time
                    fail_result.attempt_number = 0  # Set default attempt number
                    fail_result.error_code = "FutureRetrievalException"
                    fail_result.error_details = json.dumps(
                        [{"error": f"Exception during future.result(): {exc}"}]
                    )

                    # Exception during future.result() means the worker didn't complete
                    # We need to log this special case here in the main process
                    self.logdb.log_task_attempt(run_id=self.current_run_id, result=fail_result)

                    # Only update the final result if no previous result exists
                    if original_task_id not in self.results:
                        self.results[original_task_id] = fail_result
                        results_list.append(fail_result)

                        if original_task:
                            original_task.status = TaskStatus.FAILED

        self.logdb.close()

        logger.info(
            f"Parallel execution for run_id {self.current_run_id} finished. Processed {len(results_list)} tasks."
        )
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

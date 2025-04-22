"""SAPT workflow orchestrator.

This module contains the main workflow logic for SAPT calculations.
"""

# Imports for parallel execution
import concurrent.futures
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from tqdm import tqdm

from .backend import Psi4Backend, SaptBackend
from .models import Molecule, SaptResult, SaptTask, TaskStatus


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
def _execute_task_for_parallel(backend: SaptBackend, task: SaptTask) -> SaptResult:
    """Worker function to run a single task, setting thread count."""
    # Ensure Psi4 (if used) runs single-threaded within the worker process
    os.environ["OMP_NUM_THREADS"] = "1"
    # It might be necessary to re-initialize backend components here
    # if they are not process-safe or picklable, but Psi4Backend
    # relies on subprocess calls, which should be fine.
    result = backend.calculate(task)
    return result


@dataclass
class SaptWorkflow:
    """Workflow for running SAPT calculations.

    This class manages multiple SAPT tasks and executes them using the provided backend.

    Attributes:
        backend: The backend to use for SAPT calculations
        tasks: List of SAPT tasks to run
        results: Dictionary mapping task IDs to results
    """

    backend: SaptBackend = field(default_factory=get_default_backend)
    tasks: List[SaptTask] = field(default_factory=list)
    results: Dict[str, SaptResult] = field(default_factory=dict)

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

        Args:
            max_workers: Maximum number of worker processes. Defaults to os.cpu_count().

        Returns:
            Dictionary mapping task IDs to results
        """
        # Filter tasks that need to be run
        pending_tasks = [task for task in self.tasks if task.status == TaskStatus.PENDING]

        if not pending_tasks:
            print("No pending tasks to run.")
            return self.results

        print(
            f"Running {len(pending_tasks)} tasks in parallel "
            f"(max_workers={max_workers or os.cpu_count()})..."
        )

        # Ensure the main script is guarded by if __name__ == '__main__':
        # This is crucial for multiprocessing on Windows.

        with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Use executor.map to apply the function to the tasks
            # Wrap with tqdm for progress bar
            future_to_task = {
                executor.submit(_execute_task_for_parallel, self.backend, task): task
                for task in pending_tasks
            }
            results_list = []
            for future in tqdm(
                concurrent.futures.as_completed(future_to_task), total=len(pending_tasks)
            ):
                task = future_to_task[future] # This is the original task object from self.tasks
                try:
                    result = future.result()
                    self.results[task.id] = result
                    results_list.append(result)
                    # Update the status of the original task object
                    task.status = TaskStatus.COMPLETED if result.success else TaskStatus.FAILED
                except Exception as exc:
                    print(f"{task.id} generated an exception: {exc}")
                    # Create a failure result
                    fail_result = SaptResult(
                        task_id=task.id,
                        success=False,
                        error_message=str(exc),
                    )
                    self.results[task.id] = fail_result
                    results_list.append(fail_result)
                    # Update the status of the original task object
                    task.status = TaskStatus.FAILED

        print(f"Parallel execution finished. Processed {len(results_list)} tasks.")
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
    # Create a task
    task = SaptTask(
        monomer_a=monomer_a,
        monomer_b=monomer_b,
        basis_set=basis_set,
        method=method,
        additional_keywords=kwargs,
    )

    # Create a backend if none provided
    if backend is None:
        backend = get_default_backend()

    # Run the calculation
    return backend.calculate(task)

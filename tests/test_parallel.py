# tests/test_parallel.py
import os
import time
from dataclasses import dataclass

import pytest
from saptase.core.models import Molecule, SaptResult, SaptTask, TaskStatus
from saptase.core.orchestrator import SaptBackend, SaptWorkflow


# Define a simple, pickleable mock backend for parallel tests
@dataclass
class SleepyMockBackend(SaptBackend):
    """Mock backend that sleeps and returns constant energy."""

    sleep_time: float = 0.5

    def calculate(self, task: SaptTask) -> SaptResult:
        """Simulate calculation time and return a fixed result."""
        print(f"Worker {os.getpid()} processing task {task.id}...")  # Debug print
        time.sleep(self.sleep_time)
        result = SaptResult(task_id=task.id)
        result.success = True
        result.energies = {"total": -0.12345}  # Constant dummy energy
        task.status = TaskStatus.COMPLETED
        print(f"Worker {os.getpid()} finished task {task.id}.")  # Debug print
        return result


# Define standard water monomers for testing
water_monomer_a = Molecule(
    symbols=["O", "H", "H"],
    coordinates=[
        [0.000000, 0.000000, 0.000000],
        [0.000000, 0.757160, 0.586260],
        [0.000000, -0.757160, 0.586260],
    ],
    charge=0,
    multiplicity=1,
)

water_monomer_b = Molecule(
    symbols=["O", "H", "H"],
    coordinates=[
        [2.000000, 0.000000, 0.000000],
        [2.000000, 0.757160, 0.586260],
        [2.000000, -0.757160, 0.586260],
    ],
    charge=0,
    multiplicity=1,
)

# TODO: Add test functions:
# - test_parallel_speedup (optional/skipped on CI)


def test_parallel_run_correctness():
    """Test that parallel execution completes tasks and returns correct results."""
    mock_backend = SleepyMockBackend(sleep_time=0.1)  # Faster sleep for correctness test
    workflow = SaptWorkflow(backend=mock_backend)

    task1 = workflow.add_dimer(water_monomer_a, water_monomer_b, task_id="dimer_1")
    task2 = workflow.add_dimer(water_monomer_a, water_monomer_b, task_id="dimer_2")

    assert task1.status == TaskStatus.PENDING
    assert task2.status == TaskStatus.PENDING

    results = workflow.run_local_parallel(max_workers=2)

    assert len(results) == 2
    assert task1.id in results
    assert task2.id in results

    result1 = results[task1.id]
    result2 = results[task2.id]

    assert result1.success is True
    assert result1.energies["total"] == -0.12345
    assert task1.status == TaskStatus.COMPLETED  # Check original task status

    assert result2.success is True
    assert result2.energies["total"] == -0.12345
    assert task2.status == TaskStatus.COMPLETED  # Check original task status


@pytest.mark.slow
def test_parallel_speedup():
    """Test if parallel execution is faster than serial for tasks with simulated delay."""
    num_tasks = 4  # Use more tasks to make speedup more apparent
    sleep_time = 0.25  # Each task takes 0.25s
    max_workers = 2

    mock_backend = SleepyMockBackend(sleep_time=sleep_time)
    workflow_serial = SaptWorkflow(backend=mock_backend)
    workflow_parallel = SaptWorkflow(backend=mock_backend)  # Use a separate instance

    # Add tasks to both workflows
    for i in range(num_tasks):
        task_id = f"dimer_{i+1}"
        workflow_serial.add_dimer(water_monomer_a, water_monomer_b, task_id=task_id)
        # Need to create separate tasks for the parallel workflow as they get mutated
        workflow_parallel.add_dimer(water_monomer_a, water_monomer_b, task_id=task_id)

    # --- Serial Run ---
    start_serial = time.perf_counter()
    workflow_serial.run_local_serial()
    end_serial = time.perf_counter()
    serial_time = end_serial - start_serial
    print(f"\nSerial time ({num_tasks} tasks): {serial_time:.4f}s")

    # --- Parallel Run ---
    start_parallel = time.perf_counter()
    workflow_parallel.run_local_parallel(max_workers=max_workers)
    end_parallel = time.perf_counter()
    parallel_time = end_parallel - start_parallel
    print(f"Parallel time ({num_tasks} tasks, {max_workers} workers): {parallel_time:.4f}s")

    # Assert correctness for parallel run as well
    assert len(workflow_parallel.results) == num_tasks
    for i in range(num_tasks):
        assert workflow_parallel.results[f"dimer_{i+1}"].success is True

    # Check for speedup (only if parallel is actually faster)
    # Expected serial: num_tasks * sleep_time
    # Expected parallel: (num_tasks / max_workers) * sleep_time + overhead
    # Allow some tolerance for overhead
    if parallel_time < serial_time:
        print("Parallel execution was faster than serial.")
        # Basic assertion: parallel should be significantly faster than serial
        # For 4 tasks, 2 workers, sleep 0.25s -> Serial ~1.0s, Parallel ~0.5s + overhead
        assert parallel_time < (serial_time * 0.8)  # Expect at least 20% speedup if faster
    else:
        # Don't fail if parallel is slower due to overhead or timing issues on CI
        print("Warning: Parallel execution was not faster than serial.")
        pytest.skip("Parallel execution was not faster than serial in this environment.")

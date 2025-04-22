# Imports for the new test file
import pytest
import sqlite3
import json
import logging  # Import logging
from pathlib import Path
from saptase import SaptWorkflow, SaptTask, Molecule, SaptResult, TaskStatus, BASIS_LADDER # Import BASIS_LADDER from top level
from saptase.core.backend import SaptBackend
from saptase.core.errors import BasisIncompatible, ScfFailed, MemoryExceeded, SaptError

# Setup logger for tests (can be helpful for debugging mock backend)
# Place this *outside* any class or function to be module-level
logging.basicConfig(level=logging.INFO) # Use INFO or DEBUG for more verbosity
logger = logging.getLogger(__name__)

# Define a mock backend that can simulate failures
class MockFailureBackend(SaptBackend):
    """A mock backend that raises specific errors based on task state."""
    def __init__(self, fail_on_basis=None, fail_on_scf_keywords=None, fail_on_memory_keywords=None, success_on_basis=None, success_on_keywords=None):
        self.fail_on_basis = fail_on_basis
        self.fail_on_scf_keywords = fail_on_scf_keywords
        self.fail_on_memory_keywords = fail_on_memory_keywords
        self.success_on_basis = success_on_basis
        self.success_on_keywords = success_on_keywords or {}
        self.attempt_counters = {} # Track attempts per task_id

    def calculate(self, task: SaptTask) -> SaptResult:
        task_id = task.id
        # Determine the current attempt number.
        # EscalationContext manages this externally; the backend sees the modified task.
        # We simulate this by incrementing our internal counter.
        attempt = self.attempt_counters.get(task_id, 0)
        self.attempt_counters[task_id] = attempt + 1
        logger.debug(f"MockBackend: Task {task_id}, Attempt {attempt+1}, Basis {task.basis_set}, Keywords {task.additional_keywords}") # Use logger, 1-based for display

        # --- Failure Simulation Logic ---
        # Simulate BasisIncompatible on first attempt if basis matches fail_on_basis
        # Note: We check attempt == 0 because the *first* call to backend is attempt 0 in the recovery context
        if attempt == 0 and self.fail_on_basis and task.basis_set == self.fail_on_basis:
            logger.debug(f"MockBackend: Simulating BasisIncompatible for {task_id} on basis {task.basis_set}") # Use logger
            raise BasisIncompatible(f"Basis '{task.basis_set}' is incompatible (simulated).")

        # Simulate ScfFailed if specific keywords are present (indicating potential 2nd attempt recovery)
        if self.fail_on_scf_keywords and all(kw in task.additional_keywords for kw in self.fail_on_scf_keywords):
             logger.debug(f"MockBackend: Simulating ScfFailed for {task_id} due to keywords {task.additional_keywords}") # Use logger
             raise ScfFailed("SCF failed with relaxed keywords (simulated).")

        # Simulate MemoryExceeded if specific keywords are present (indicating potential 3rd attempt recovery)
        if self.fail_on_memory_keywords and all(kw in task.additional_keywords for kw in self.fail_on_memory_keywords):
             logger.debug(f"MockBackend: Simulating MemoryExceeded for {task_id} due to keywords {task.additional_keywords}") # Use logger
             raise MemoryExceeded("Memory exceeded with reduced request (simulated).")

        # --- Success Condition ---
        # Succeed if basis matches success_on_basis
        if self.success_on_basis and task.basis_set == self.success_on_basis:
            logger.debug(f"MockBackend: Simulating Success for {task_id} on basis {task.basis_set}") # Use logger
            result = SaptResult(
                task_id=task.id,
                success=True,
                energies={"SAPT0": -0.123}, # Dummy energy
                basis_set=task.basis_set,  # Populate from the task that succeeded
                method=task.method         # Populate from the task that succeeded
            )
            result.attempt_number = attempt # Pass the 0-based attempt index of this successful call
            return result
        # Succeed if keywords match success_on_keywords
        if self.success_on_keywords and all(kw in task.additional_keywords for kw in self.success_on_keywords):
            logger.debug(f"MockBackend: Simulating Success for {task_id} based on keywords {task.additional_keywords}") # Use logger
            result = SaptResult(
                task_id=task.id,
                success=True,
                energies={"SAPT0": -0.456}, # Dummy energy
                basis_set=task.basis_set,  # Populate from the task that succeeded
                method=task.method         # Populate from the task that succeeded
            )
            result.attempt_number = attempt # Pass the 0-based attempt index of this successful call
            return result

        # Default: Raise an unexpected error if no condition met (indicates test setup issue)
        logger.error(f"MockBackend: Reached unexpected state for task {task_id} on attempt {attempt+1} with basis {task.basis_set} and keywords {task.additional_keywords}") # Use logger
        raise RuntimeError(f"MockBackend reached unexpected state for task {task.id} on attempt {attempt+1}")

# Fixture for a sample task
@pytest.fixture
def sample_task():
    """Provides a basic SaptTask."""
    # Using smaller molecules for simplicity if needed
    mol_a_xyz = "1\nComment line\nH 0 0 0"
    mol_b_xyz = "1\nComment line\nH 0 0 1"
    mol_a = Molecule.from_xyz_string(mol_a_xyz)
    mol_b = Molecule.from_xyz_string(mol_b_xyz)
    # Start with a basis that we expect to fail initially
    initial_basis = "jun-cc-pvtz" # Match case in BASIS_LADDER
    return SaptTask(monomer_a=mol_a, monomer_b=mol_b, basis_set=initial_basis, method="sapt0", id="simple_dimer_test")

# Fixture to provide a clean LogDb for each test
@pytest.fixture
def log_db(tmp_path):
    """Provides an initialized LogDb instance path in a temporary directory."""
    db_path = tmp_path / "test_runs.sqlite"
    # Ensure the directory exists, Workflow will initialize the DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink() # Ensure clean DB for each test
    yield db_path
    # Clean up if needed, though tmp_path usually handles it
    # if db_path.exists():
    #     db_path.unlink()

# --- Test Cases ---

def test_orchestrator_recover_basis_incompatible(sample_task, log_db):
    """
    Test recovery from BasisIncompatible by switching to the next smaller basis.
    Simulates failure on jun-cc-pvtz and success on jun-cc-pvdz.
    """
    initial_basis = "jun-cc-pvtz" # Match case in BASIS_LADDER
    # Find the actual previous basis from the BASIS_SETS dictionary
    basis_levels = BASIS_LADDER # Use the list directly
    try:
        initial_index = basis_levels.index(initial_basis)
        if initial_index == 0:
            pytest.fail("Initial basis is already the smallest, cannot test recovery.")
        recovered_basis = basis_levels[initial_index - 1]
        logger.info(f"Testing basis recovery: {initial_basis} -> {recovered_basis}")
    except ValueError:
        pytest.fail(f"Initial basis '{initial_basis}' not found in BASIS_SETS.")


    # Configure backend to fail on initial basis, succeed on recovered basis
    backend = MockFailureBackend(fail_on_basis=initial_basis, success_on_basis=recovered_basis)

    # Setup workflow
    workflow = SaptWorkflow(backend=backend, db_path=log_db)
    sample_task.basis_set = initial_basis # Ensure task starts with the failing basis
    workflow.add_task(sample_task)

    # Run workflow
    results = workflow.run_local_parallel(max_workers=1) # Run with 1 worker for simplicity

    # --- Assertions ---
    # 1. Check final result success and details
    assert sample_task.id in results
    final_result = results[sample_task.id]
    assert final_result.success is True, f"Task should have succeeded but failed. Result: {final_result}"
    assert final_result.energies is not None, "Successful result should have energies."
    # Check attempt number directly on the result (if backend provides it, like our mock)
    # Note: The final returned result corresponds to the *last successful* run's ID and attempt number.
    assert final_result.task_id == f"{sample_task.id}_retry_1", "Final result ID should match the retry task ID."
    assert final_result.attempt_number == 1, "Final successful attempt should be attempt 1 (the first retry)."
    assert final_result.basis_set == recovered_basis, f"Successful result should have basis {recovered_basis}, got {final_result.basis_set}"
    assert final_result.method == sample_task.method # Method shouldn't change in this test

    # 2. Check task status in workflow object
    # Find the task object within the workflow's task list
    task_in_workflow = next((t for t in workflow.tasks if t.id == sample_task.id), None)
    assert task_in_workflow is not None
    assert task_in_workflow.status == TaskStatus.COMPLETED

    # 3. Check database logs
    # Allow workflow's LogDb instance to close properly before querying
    # This might require a small delay or ensuring the workflow context manager handles it.
    # For simplicity here, assume logdb is closed or flushed. Re-open connection:
    assert log_db.exists(), "Database file was not created."
    conn = sqlite3.connect(log_db)
    conn.row_factory = sqlite3.Row # Return rows accessible by column name
    cursor = conn.cursor()
    # Ensure we select all relevant columns, especially the new ones
    cursor.execute("""
        SELECT run_id, task_id, attempt_number, status, error_code, error_details, basis_set, method, elapsed_time, error_message
        FROM task_log
        WHERE task_id LIKE ?
        ORDER BY attempt_number
    """, (f"{sample_task.id}%",))
    logs = cursor.fetchall()
    columns = [col[0] for col in cursor.description] # Get column names
    conn.close()


    assert len(logs) == 2, f"Expected 2 log entries for task prefix '{sample_task.id}', found {len(logs)}."


    # Find log entries based on exact task ID
    initial_log = next((log for log in logs if log['task_id'] == sample_task.id), None)
    retry_log = next((log for log in logs if log['task_id'] == f"{sample_task.id}_retry_1"), None)


    assert initial_log is not None, f"Log entry for initial task ID '{sample_task.id}' not found."
    assert retry_log is not None, f"Log entry for retry task ID '{sample_task.id}_retry_1' not found."


    # Check initial failed attempt log
    assert initial_log['task_id'] == sample_task.id
    assert initial_log['status'] == TaskStatus.FAILED.name # Status should be FAILED
    assert initial_log['basis_set'] == initial_basis # Check basis set used
    assert initial_log['error_code'] == 'BasisIncompatible' # Check recorded error


    # Check successful retry attempt log
    assert retry_log['task_id'] == f"{sample_task.id}_retry_1"
    assert retry_log['status'] == TaskStatus.COMPLETED.name # Status should be COMPLETED
    assert retry_log['basis_set'] == recovered_basis # Check recovered basis set
    assert retry_log['error_code'] is None # No error on successful run

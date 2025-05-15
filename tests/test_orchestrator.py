# Imports for the new test file
import logging  # Import logging
import sqlite3

import pytest
from saptase import (
    BASIS_LADDER,
    Molecule,
    SaptResult,
    SaptTask,
    SaptWorkflow,
    TaskStatus,
)  # Import BASIS_LADDER from top level
from saptase.core.backend import SaptBackend
from saptase.core.errors import BasisIncompatible, MemoryExceeded, SaptError, ScfFailed

# Setup logger for tests (can be helpful for debugging mock backend)
# Place this *outside* any class or function to be module-level
logging.basicConfig(level=logging.INFO)  # Use INFO or DEBUG for more verbosity
logger = logging.getLogger(__name__)


# Define a mock backend that can simulate failures
class MockFailureBackend(SaptBackend):
    """A mock backend that raises specific errors based on task state."""

    def __init__(
        self,
        fail_on_basis=None,
        fail_scf_original_ids=None,
        fail_memory_original_ids=None,
        success_on_basis=None,
        success_on_keywords=None,
        fail_always_original_ids=None,
    ):
        self.fail_on_basis = fail_on_basis  # Basis to fail on first attempt
        self.fail_scf_original_ids = (
            fail_scf_original_ids or []
        )  # Original IDs to fail SCF on first attempt
        self.fail_memory_original_ids = (
            fail_memory_original_ids or []
        )  # Original IDs to fail Memory on first attempt
        self.success_on_basis = success_on_basis  # Basis to succeed on (usually for basis recovery)
        self.success_on_keywords = (
            success_on_keywords or {}
        )  # Keywords needed for success (usually for SCF/Mem recovery)
        self.fail_always_original_ids = (
            fail_always_original_ids or []
        )  # Original IDs to always fail, simulating unrecoverable errors
        self.attempt_counters = {}  # Track attempts per original task ID prefix

    def calculate(self, task: SaptTask) -> SaptResult:
        # Extract original ID prefix (strip _retry_N)
        original_task_id = task.id.split("_retry_")[0]

        attempt = self.attempt_counters.get(original_task_id, 0)
        self.attempt_counters[original_task_id] = attempt + 1
        logger.debug(
            f"MockBackend: Task {task.id} (Original: {original_task_id}), Attempt {attempt+1}, Basis {task.basis_set}, Keywords {task.additional_keywords}"
        )

        # Simulate always failing tasks first
        if original_task_id in self.fail_always_original_ids:
            logger.debug(f"MockBackend: Simulating persistent failure for {task.id}")
            raise ScfFailed(
                f"Simulating persistent failure for {original_task_id}, attempt {attempt+1}"
            )  # Use ScfFailed for simplicity

        # --- Failure Simulation Logic (Attempt 0 = First Call) ---
        if attempt == 0:
            if original_task_id in self.fail_scf_original_ids:
                logger.debug(f"MockBackend: Simulating ScfFailed for {task.id} on attempt 1")
                raise ScfFailed("SCF failed on initial attempt (simulated).")
            if self.fail_on_basis and task.basis_set == self.fail_on_basis:
                logger.debug(
                    f"MockBackend: Simulating BasisIncompatible for {task.id} on basis {task.basis_set}"
                )
                raise BasisIncompatible(f"Basis '{task.basis_set}' is incompatible (simulated).")
            if original_task_id in self.fail_memory_original_ids:
                logger.debug(f"MockBackend: Simulating MemoryExceeded for {task.id} on attempt 1")
                raise MemoryExceeded("Memory exceeded on initial attempt (simulated).")
        # --- End Failure Logic for Attempt 0 ---

        # --- Success Conditions (Usually apply on retries, i.e., attempt > 0) ---
        # Check for success based on keywords (e.g., SCF recovery added level_shift)
        if self.success_on_keywords and all(
            kw in task.additional_keywords
            and task.additional_keywords[kw] == self.success_on_keywords[kw]
            for kw in self.success_on_keywords
        ):
            logger.debug(
                f"MockBackend: Simulating Success for {task.id} based on keywords {task.additional_keywords}"
            )
            result = SaptResult(
                task_id=task.id,
                success=True,
                energies={"SAPT0 TOTAL ENERGY": -0.456},  # Dummy energy
                basis_set=task.basis_set,
                method=task.method,
            )
            result.attempt_number = attempt  # Pass the 0-based attempt index
            return result

        # Check for success based on basis (e.g., Basis recovery changed basis)
        if self.success_on_basis and task.basis_set == self.success_on_basis:
            logger.debug(f"MockBackend: Simulating Success for {task.id} on basis {task.basis_set}")
            result = SaptResult(
                task_id=task.id,
                success=True,
                energies={"SAPT0 TOTAL ENERGY": -0.123},  # Dummy energy
                basis_set=task.basis_set,
                method=task.method,
            )
            result.attempt_number = attempt
            return result

        # --- Fallback Failure (If retry attempt doesn't meet success criteria) ---
        if attempt > 0:
            logger.debug(
                f"MockBackend: Simulating failure on retry attempt {attempt+1} for task {task.id} as success conditions not met."
            )
            # Re-raise an appropriate error, maybe based on original failure type?
            # For now, raise ScfFailed if it was the initial trigger, otherwise generic.
            if original_task_id in self.fail_scf_original_ids:
                raise ScfFailed(f"Retry attempt {attempt+1} failed (simulated).")
            elif original_task_id in self.fail_memory_original_ids:
                raise MemoryExceeded(f"Retry attempt {attempt+1} failed (simulated).")
            else:  # Includes basis retries that didn't hit success_on_basis
                raise SaptError(f"Retry attempt {attempt+1} failed unexpectedly (simulated).")

        # Default: Success if it's attempt 0 and no failure was triggered
        logger.debug(f"MockBackend: Simulating default success for {task.id} on attempt 1")
        result = SaptResult(
            task_id=task.id,
            success=True,
            energies={"SAPT0 TOTAL ENERGY": -0.789},  # Dummy energy
            basis_set=task.basis_set,
            method=task.method,
        )
        result.attempt_number = attempt
        return result


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
    initial_basis = "jun-cc-pvtz"  # Match case in BASIS_LADDER
    return SaptTask(
        monomer_a=mol_a,
        monomer_b=mol_b,
        basis_set=initial_basis,
        method="sapt0",
        id="simple_dimer_test",
    )


# Fixture to provide a clean LogDb for each test
@pytest.fixture
def log_db(tmp_path):
    """Provides an initialized LogDb instance path in a temporary directory."""
    db_path = tmp_path / "test_runs.sqlite"
    # Ensure the directory exists, Workflow will initialize the DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()  # Ensure clean DB for each test
    return db_path
    # Clean up if needed, though tmp_path usually handles it
    # if db_path.exists():
    #     db_path.unlink()


# --- Test Cases ---


def test_orchestrator_recover_basis_incompatible(sample_task, log_db):
    """
    Test recovery from BasisIncompatible by escalating to the next larger basis.
    Simulates failure on jun-cc-pvdz and success on aug-cc-pvdz.
    """
    # Initial basis is the first in the ladder, to test escalation.
    initial_basis = BASIS_LADDER[0]  # e.g., "jun-cc-pvdz"
    sample_task.basis_set = initial_basis

    # Determine the expected escalated basis
    # The recovery strategy recover_basis_incompatible will use get_next_basis.
    escalated_basis = None
    if len(BASIS_LADDER) > 1:
        escalated_basis = BASIS_LADDER[1]  # e.g., "aug-cc-pvdz"
    else:
        pytest.fail("BASIS_LADDER needs at least two rungs to test escalation.")

    logger.info(f"Testing basis recovery (escalation): {initial_basis} -> {escalated_basis}")

    # Configure backend to fail on initial basis, succeed on escalated basis
    backend = MockFailureBackend(fail_on_basis=initial_basis, success_on_basis=escalated_basis)

    # Setup workflow
    workflow = SaptWorkflow(backend=backend, db_path=log_db)
    workflow.add_task(sample_task)

    # Run workflow
    results = workflow.run_local_parallel(max_workers=1)  # Run with 1 worker for simplicity

    # --- Assertions ---
    # 1. Check final result success and details
    assert sample_task.id in results
    final_result = results[sample_task.id]
    assert (
        final_result.success is True
    ), f"Task should have succeeded but failed. Result: {final_result}"
    assert final_result.energies is not None, "Successful result should have energies."
    # Check attempt number directly on the result (if backend provides it, like our mock)
    # Note: The final returned result corresponds to the *last successful* run's ID and attempt number.
    assert (
        final_result.task_id == f"{sample_task.id}_retry_1"
    ), "Final result ID should match the retry task ID."
    assert (
        final_result.attempt_number
        == 1  # First retry (0-indexed in backend, but context makes it 1st retry)
    ), "Final successful attempt should be attempt 1 (the first retry)."
    assert (
        final_result.basis_set == escalated_basis
    ), f"Successful result should have basis {escalated_basis}, got {final_result.basis_set}"
    assert final_result.method == sample_task.method  # Method shouldn't change in this test

    # 2. Check task status in workflow object
    task_in_workflow = next((t for t in workflow.tasks if t.id == sample_task.id), None)
    assert task_in_workflow is not None
    assert task_in_workflow.status == TaskStatus.COMPLETED

    # 3. Check database logs
    # Allow workflow's LogDb instance to close properly before querying
    # This might require a small delay or ensuring the workflow context manager handles it.
    # For simplicity here, assume logdb is closed or flushed. Re-open connection:
    assert log_db.exists(), "Database file was not created."
    conn = sqlite3.connect(log_db)
    conn.row_factory = sqlite3.Row  # Return rows accessible by column name
    cursor = conn.cursor()
    # Ensure we select all relevant columns, especially the new ones
    cursor.execute(
        """
        SELECT run_id, task_id, attempt_number, status, error_code, error_details, basis_set, method, elapsed_time, error_message
        FROM task_log
        WHERE task_id LIKE ?
        ORDER BY attempt_number
    """,
        (f"{sample_task.id}%",),
    )
    logs = cursor.fetchall()
    conn.close()

    assert (
        len(logs) == 2
    ), f"Expected 2 log entries for task prefix '{sample_task.id}', found {len(logs)}."

    # Find log entries based on exact task ID
    initial_log = next((log for log in logs if log["task_id"] == sample_task.id), None)
    retry_log = next((log for log in logs if log["task_id"] == f"{sample_task.id}_retry_1"), None)

    assert initial_log is not None, f"Log entry for initial task ID '{sample_task.id}' not found."
    assert (
        retry_log is not None
    ), f"Log entry for retry task ID '{sample_task.id}_retry_1' not found."

    # Check initial failed attempt log
    assert initial_log["task_id"] == sample_task.id
    assert initial_log["status"] == TaskStatus.FAILED.name  # Status should be FAILED
    assert initial_log["basis_set"] == initial_basis  # Check basis set used
    assert initial_log["error_code"] == "BasisIncompatible"  # Check recorded error

    # Check successful retry attempt log
    assert retry_log["task_id"] == f"{sample_task.id}_retry_1"
    assert retry_log["status"] == TaskStatus.COMPLETED.name  # Status should be COMPLETED
    assert retry_log["basis_set"] == escalated_basis  # Check recovered basis set
    assert retry_log["error_code"] is None  # No error on successful run


def test_orchestrator_recover_scf_failed(sample_task, log_db):
    """
    Test recovery from ScfFailed by applying recovery keywords (e.g., level_shift).
    Simulates ScfFailed on first attempt, succeeds on second with keywords.
    """
    # Define the keywords expected to be added by the first SCF recovery strategy
    # IMPORTANT: Verify this against saptase/recovery/escalate.py LADDER[0]
    expected_recovery_keywords = {"level_shift": 0.5}

    # Configure backend to fail SCF for this task ID on first attempt,
    # and succeed if the expected keywords are present on a subsequent attempt.
    backend = MockFailureBackend(
        fail_scf_original_ids=[sample_task.id], success_on_keywords=expected_recovery_keywords
    )

    # Setup workflow
    workflow = SaptWorkflow(backend=backend, db_path=log_db)
    workflow.add_task(sample_task)  # Task starts with no special keywords

    # Run workflow
    results = workflow.run_local_parallel(max_workers=1)

    # --- Assertions ---
    # 1. Check final result success and details
    assert sample_task.id in results
    final_result = results[sample_task.id]
    assert (
        final_result.success is True
    ), f"Task should have succeeded but failed. Result: {final_result}"
    assert final_result.energies is not None
    assert (
        final_result.task_id == f"{sample_task.id}_retry_1"
    ), "Final result ID should match the retry task ID."
    # The successful attempt is the first retry (index 1)
    assert (
        final_result.attempt_number == 1
    ), f"Final successful attempt should be attempt 1, got {final_result.attempt_number}."
    assert final_result.basis_set == sample_task.basis_set  # Basis shouldn't change
    assert final_result.method == sample_task.method  # Method shouldn't change

    # 2. Check task status in workflow object
    task_in_workflow = next((t for t in workflow.tasks if t.id == sample_task.id), None)
    assert task_in_workflow is not None
    assert task_in_workflow.status == TaskStatus.COMPLETED

    # 3. Check database logs
    assert log_db.exists(), "Database file was not created."
    conn = sqlite3.connect(log_db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT task_id, attempt_number, status, error_code, basis_set, method
        FROM task_log WHERE task_id LIKE ? ORDER BY attempt_number
    """,
        (f"{sample_task.id}%",),
    )
    logs = cursor.fetchall()
    conn.close()

    assert len(logs) == 2, f"Expected 2 log entries, found {len(logs)}."

    initial_log = next((log for log in logs if log["task_id"] == sample_task.id), None)
    retry_log = next((log for log in logs if log["task_id"] == f"{sample_task.id}_retry_1"), None)

    assert initial_log is not None, "Log for initial task ID not found."
    assert retry_log is not None, "Log for retry task ID not found."

    # Check initial failed attempt log
    assert initial_log["status"] == TaskStatus.FAILED.name
    assert initial_log["error_code"] == "ScfFailed"
    assert initial_log["basis_set"] == sample_task.basis_set  # Initial basis

    # Check successful retry attempt log
    assert retry_log["status"] == TaskStatus.COMPLETED.name
    assert retry_log["error_code"] is None  # No error on success
    assert retry_log["basis_set"] == sample_task.basis_set  # Basis unchanged
    # We don't explicitly log the keywords applied, but success implies they were used by the mock backend.


def test_orchestrator_exhaust_ladder(sample_task, log_db):
    """
    Test that a task fails permanently if all recovery steps are exhausted.
    Simulates persistent failure across all attempts.
    """
    # Configure backend to always fail for this task ID, regardless of keywords/basis
    backend = MockFailureBackend(fail_always_original_ids=[sample_task.id])

    # Setup workflow
    workflow = SaptWorkflow(backend=backend, db_path=log_db)
    # Modify max_retries if needed for testing, but default should cover ladder
    # workflow.max_retries = 2 # Example: Limit retries for quicker test
    workflow.add_task(sample_task)

    # Run workflow
    results = workflow.run_local_parallel(max_workers=1)

    # --- Assertions ---
    # 1. Check final result indicates failure
    assert sample_task.id in results
    final_result = results[sample_task.id]
    assert final_result.success is False, "Task should have failed permanently."
    # The error message/code might correspond to the *last* attempted failure type
    # In our mock, fail_always raises ScfFailed, so we expect that.
    assert final_result.error_message is not None
    assert (
        final_result.error_code == "ScfFailed"
    ), f"Expected final error code 'ScfFailed', got '{final_result.error_code}'"
    # We don't have attempt_number on failed results currently.

    # 2. Check task status in workflow object
    task_in_workflow = next((t for t in workflow.tasks if t.id == sample_task.id), None)
    assert task_in_workflow is not None
    assert task_in_workflow.status == TaskStatus.FAILED, "Task status should be FAILED."

    # 3. Check database logs
    assert log_db.exists(), "Database file was not created."
    conn = sqlite3.connect(log_db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT task_id, attempt_number, status, error_code
        FROM task_log WHERE task_id LIKE ? ORDER BY attempt_number
    """,
        (f"{sample_task.id}%",),
    )
    logs = cursor.fetchall()
    conn.close()

    # With our implementation, we expect 2 log entries:
    # 1. The original task attempt (which fails)
    # 2. The first retry attempt (which also fails) leading to exhaustion
    # The max_attempts = 3 means 1 initial + 2 retries, but the code doesn't
    # necessarily use all retries if a recovery strategy can't be found
    expected_logs = 2
    assert (
        len(logs) == expected_logs
    ), f"Expected {expected_logs} log entries for the task and its retries, found {len(logs)}."

    # Check the status and error codes of the logs
    assert logs[0]["status"] == TaskStatus.FAILED.name, "First attempt should be FAILED"

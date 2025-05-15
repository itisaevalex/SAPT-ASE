# tests/test_recovery.py
"""Tests for the error recovery and escalation logic."""

import copy

import pytest
from saptase.core.errors import BasisIncompatible, MemoryExceeded, ScfFailed
from saptase.core.models import Molecule, SaptTask
from saptase.recovery.escalate import LADDER, EscalationContext


# Fixture for a standard SaptTask
@pytest.fixture
def sample_task():
    """Provides a sample SaptTask for testing recovery."""
    # Use a basis that has a predecessor in the default ladder
    basis_set = "aug-cc-pvdz"  # Predecessor is jun-cc-pvdz
    mol_a = Molecule(name="mol_a", symbols=["H"], coordinates=[[0.0, 0.0, 0.0]])
    mol_b = Molecule(name="mol_b", symbols=["He"], coordinates=[[0.0, 0.0, 2.0]])
    # Setup initial keywords for testing modifications later
    initial_keywords = {
        "d_convergence": 1e-7,
        "e_convergence": 1e-7,  # Include e_convergence as strategy modifies it
        "maxiter": 50,
        "memory": "10 GB",
    }
    return SaptTask(
        id="test_task_01",
        monomer_a=mol_a,
        monomer_b=mol_b,
        basis_set=basis_set,
        method="sapt0",
        additional_keywords=copy.deepcopy(initial_keywords),  # Use deepcopy
    )


# --- EscalationContext Tests --- #


def test_escalation_context_init(sample_task):
    """Test basic initialization of EscalationContext."""
    context = EscalationContext(sample_task)
    assert context.original_task == sample_task
    assert context.attempt_count == 0
    assert context.max_attempts == len(LADDER)  # Max attempts based on ladder length
    assert context.last_error is None
    assert not context.history


def test_escalation_context_can_retry_initial(sample_task):
    """Test can_retry before any attempts."""
    context = EscalationContext(sample_task)
    # Initially, can retry as no attempts made
    assert context.can_retry(BasisIncompatible("Test")) is True


def test_escalation_context_apply_basis_incompatible(sample_task):
    """Test applying the basis incompatibility recovery strategy."""
    context = EscalationContext(sample_task)
    error = BasisIncompatible(f"Basis '{sample_task.basis_set}' not suitable")

    assert context.can_retry(error) is True
    modified_task = context.apply()

    assert context.attempt_count == 1
    assert context.last_error == error
    assert modified_task.id == "test_task_01_retry_1"
    # Expect basis to escalate from aug-cc-pvdz to jun-cc-pvtz
    assert modified_task.basis_set == "jun-cc-pvtz"
    assert (
        modified_task.additional_keywords.get("recovery_strategy")
        == "recover_basis_incompatible_escalate"
    )
    assert len(context.history) == 1
    assert context.history[0]["strategy_name"] == "recover_basis_incompatible"
    assert context.history[0]["error_type"] == "BasisIncompatible"


def test_escalation_context_apply_scf_failed(sample_task):
    """Test applying the SCF failure recovery strategy.
    NOTE: This test now checks the *first* attempt, which applies recover_basis_incompatible.
    """
    # Get initial values from fixture for comparison
    initial_d_conv = sample_task.additional_keywords["d_convergence"]
    initial_maxiter = sample_task.additional_keywords["maxiter"]

    context = EscalationContext(sample_task)
    error = ScfFailed("SCF failed to converge")

    assert context.can_retry(error) is True
    modified_task = context.apply()

    assert context.attempt_count == 1
    assert context.last_error == error
    assert modified_task.id == "test_task_01_retry_1"  # Check correct ID
    # On 1st attempt, the first strategy in LADDER for ScfFailed is recover_basis_incompatible
    assert modified_task.basis_set == "jun-cc-pvtz"  # Basis should change from aug-cc-pvdz
    assert (
        modified_task.additional_keywords.get("d_convergence") == initial_d_conv
    )  # SCF keywords untouched
    assert modified_task.additional_keywords.get("maxiter") == initial_maxiter
    assert (
        modified_task.additional_keywords.get("recovery_strategy")
        == "recover_basis_incompatible_escalate"
    )
    assert len(context.history) == 1


def test_escalation_context_apply_memory_exceeded(sample_task):
    """Test applying the memory exceeded recovery strategy.
    NOTE: This test now checks the *first* attempt, which applies recover_basis_incompatible.
    """
    # Get initial memory from fixture for comparison
    initial_memory = sample_task.additional_keywords["memory"]
    context = EscalationContext(sample_task)
    error = MemoryExceeded("Calculation requested 12 GB, only 10 GB available")

    assert context.can_retry(error) is True
    modified_task = context.apply()

    assert context.attempt_count == 1
    assert context.last_error == error
    assert modified_task.id == "test_task_01_retry_1"
    # On 1st attempt, the first strategy in LADDER for MemoryExceeded is recover_basis_incompatible
    assert modified_task.basis_set == "jun-cc-pvtz"  # Basis should change from aug-cc-pvdz
    assert (
        modified_task.additional_keywords.get("memory") == initial_memory
    )  # Memory untouched by this strategy
    assert (
        modified_task.additional_keywords.get("recovery_strategy")
        == "recover_basis_incompatible_escalate"
    )
    assert len(context.history) == 1


def test_escalation_context_max_retries(sample_task):
    """Test that can_retry returns False after max attempts."""
    # Use a non-modifying error/strategy for simplicity if needed, or accept changes
    context = EscalationContext(sample_task)
    error = ScfFailed("SCF keeps failing repeatedly")  # Use any applicable error

    # Simulate reaching max attempts
    for i in range(context.max_attempts):
        assert context.can_retry(error) is True, f"Should be able to retry on attempt {i+1}"
        # Apply strategy to increment count and potentially modify task
        # Use the error relevant to the *first* strategy in the ladder if applicable
        # For simplicity, we'll use the same error, assuming it persists.
        # A more complex test could alternate errors.
        # Use the context.apply() method to apply the recovery strategy
        _ = context.apply(error)  # Apply strategy based on error

    # After max_attempts, can_retry should be False
    assert context.can_retry(error) is False, "Should not be able to retry after max attempts"

    # Check history length matches max attempts
    assert len(context.history) == context.max_attempts


# --- Tests for specific ladder steps --- #


def test_escalation_context_apply_second_attempt_scf(sample_task):
    """Test that the second strategy (SCF relax) is applied on attempt 2."""
    context = EscalationContext(sample_task)
    initial_d_conv = sample_task.additional_keywords["d_convergence"]
    initial_e_conv = sample_task.additional_keywords["e_convergence"]
    initial_maxiter = sample_task.additional_keywords["maxiter"]
    original_basis = sample_task.basis_set

    # --- Attempt 1 (Basis) --- #
    error1 = BasisIncompatible("First error")
    assert context.can_retry(error1) is True  # Sets last_error
    task_retry1 = context.apply()
    assert context.attempt_count == 1
    assert task_retry1.basis_set == "jun-cc-pvtz"  # Basis changed from aug-cc-pvdz
    assert (
        task_retry1.additional_keywords.get("recovery_strategy")
        == "recover_basis_incompatible_escalate"
    )

    # --- Attempt 2 (SCF) --- #
    error2 = ScfFailed("Second error")
    # EscalationContext internally uses original_task for the deepcopy when applying.
    # We test that the correct strategy (LADDER[1]) is selected and applied to original_task.
    assert context.can_retry(error2) is True  # Sets last_error to error2
    task_retry2 = context.apply()
    assert context.attempt_count == 2
    assert context.last_error == error2

    # Check SCF strategy was applied (LADDER[1]) vs original task keywords
    assert task_retry2.additional_keywords.get("d_convergence") > initial_d_conv
    assert task_retry2.additional_keywords.get("e_convergence") > initial_e_conv
    assert task_retry2.additional_keywords.get("maxiter") > initial_maxiter
    assert task_retry2.additional_keywords.get("recovery_strategy") == "recover_scf_failed_simple"
    # Check basis remains from original task (strategy copies original_task)
    assert task_retry2.basis_set == original_basis

    assert len(context.history) == 2
    assert context.history[1]["strategy_name"] == "recover_scf_failed_simple"


def test_escalation_context_apply_third_attempt_memory(sample_task):
    """Test that the third strategy (Memory reduce) is applied on attempt 3."""
    context = EscalationContext(sample_task)
    initial_memory_str = sample_task.additional_keywords["memory"]
    initial_memory_val = float(initial_memory_str.split()[0])
    original_basis = sample_task.basis_set
    initial_d_conv = sample_task.additional_keywords["d_convergence"]

    # --- Attempt 1 (Basis) --- #
    assert context.can_retry(BasisIncompatible("E1"))
    _ = context.apply()
    assert context.attempt_count == 1

    # --- Attempt 2 (SCF) --- #
    assert context.can_retry(ScfFailed("E2"))
    _ = context.apply()
    assert context.attempt_count == 2

    # --- Attempt 3 (Memory) --- #
    error3 = MemoryExceeded("Third error")
    assert context.can_retry(error3) is True  # Sets last_error to error3
    task_retry3 = context.apply()
    assert context.attempt_count == 3
    assert context.last_error == error3

    # Check Memory strategy was applied (LADDER[2]) vs original task keywords
    assert "GB" in task_retry3.additional_keywords.get("memory", "")
    assert (
        float(task_retry3.additional_keywords["memory"].split()[0]) < initial_memory_val
    )  # Reduced
    expected_memory = initial_memory_val * 0.8  # Strategy reduces by 20%
    assert abs(float(task_retry3.additional_keywords["memory"].split()[0]) - expected_memory) < 1e-9
    assert task_retry3.additional_keywords.get("recovery_strategy") == "recover_memory_exceeded"
    # Check basis and SCF keywords remain from original task (due to deepcopy in apply)
    assert task_retry3.basis_set == original_basis
    assert task_retry3.additional_keywords.get("d_convergence") == initial_d_conv

    assert len(context.history) == 3
    assert context.history[2]["strategy_name"] == "recover_memory_exceeded"

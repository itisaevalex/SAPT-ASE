# tests/test_adaptive.py
"""
Tests for the AdaptiveWorkflow functionality.
"""

from typing import Any, Dict, Optional, TYPE_CHECKING, List, Tuple, Union

import numpy as np
import pytest
from saptase.core.backend import SaptBackend
from saptase.core.basis import BASIS_LADDER, get_basis_rung, get_next_basis
from saptase.core.models import Molecule, SaptResult, SaptTask, TaskStatus
from saptase.core.orchestrator import run_adaptive_workflow
from saptase.workflows.adaptive import AdaptiveWorkflow
from unittest.mock import MagicMock, patch

# Helper function to create dummy SaptResult objects for testing convergence
INTERNAL_KEY_MAP = {
    "SAPT0 Total Energy": "total",
    "Electrostatics": "elst",
    "Exchange": "exch",
    "Induction": "ind",
    "Dispersion": "disp",
}


def create_dummy_result(
    task_id: str, energies: Dict[str, float], success: bool = True
) -> SaptResult:
    # Rename keys to match the internal mapping used in _check_convergence
    simplified_energies = {
        INTERNAL_KEY_MAP.get(k, k.lower().replace(" ", "_")): v for k, v in energies.items()
    }
    result = SaptResult(task_id=task_id, success=success)
    result.energies = simplified_energies  # Use simplified keys
    return result


# Dummy task for initializing AdaptiveWorkflow
dummy_symbols = ["O", "H", "H"]
dummy_coords = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, 1.0, 0.0]])
mol_a = Molecule(symbols=dummy_symbols, coordinates=dummy_coords)
mol_b = Molecule(symbols=dummy_symbols, coordinates=dummy_coords + np.array([2.0, 0.0, 0.0]))
dummy_task = SaptTask(id="dummy", monomer_a=mol_a, monomer_b=mol_b, basis_set=BASIS_LADDER[0])


# Mock backend for testing run_adaptive
class MockAdaptiveBackend(SaptBackend):
    """
    A mock backend that returns predefined results based on the basis set.
    Simulates the adaptive workflow process.
    """

    def __init__(
        self, results_by_basis: Dict[str, Dict[str, float]], fail_on_basis: Optional[str] = None
    ):
        # Store results with lowercase keys for case-insensitive lookup
        self._results = {k.lower(): v for k, v in results_by_basis.items()}
        self.fail_on_basis = fail_on_basis.lower() if fail_on_basis else None  # Store lowercase
        self.call_history = []  # Track calls
        # Basic component map for dummy results
        self.component_map = {
            "SAPT0 Total Energy": "sapt_total",
            "Electrostatics": "elst",
            "Exchange": "exch",
            "Induction": "ind",
            "Dispersion": "disp",
        }

    def calculate(self, task: SaptTask) -> SaptResult:
        """Return a predefined result or simulate failure."""
        self.call_history.append(task.basis_set)  # Record basis called with
        # Lookup using lowercase basis
        basis_key = task.basis_set.lower()
        if basis_key in self._results:
            # Simulate successful result with simplified energies
            # Convert simplified keys back to full names if needed, or adjust tests
            raw_energies = self._results[basis_key]
            # Ensure we have a 'total' if possible
            if "total" not in raw_energies:
                # Quick sum for mock purposes if 'total' isn't specified
                raw_energies["total"] = sum(v for k, v in raw_energies.items() if k != "total")

            # Construct a minimal SaptResult
            # Note: We need to ensure the keys match what _check_convergence expects
            # For simplicity, let's assume the mock results keys are already simplified
            result = SaptResult(
                task_id=task.id, energies=raw_energies, success=True  # Store the raw dictionary
            )
            # Mock the method directly on the instance for testing
            result.get_sapt_component_map = lambda: self.component_map
            task.status = TaskStatus.COMPLETED
            return result
        elif basis_key == self.fail_on_basis:
            # Simulate failure
            result = SaptResult(
                task_id=task.id,
                success=False,
                error_message=f"Simulated failure for basis {task.basis_set}",
            )
            task.status = TaskStatus.FAILED
            return result
        else:
            # Basis not defined in mock results - treat as error? Or default?
            # For testing, let's treat it as a failure.
            result = SaptResult(
                task_id=task.id,
                success=False,
                error_message=f"Mock backend has no result defined for basis {task.basis_set}",
            )
            task.status = TaskStatus.FAILED
            return result

    # Implement abstract methods if SaptBackend requires them (assume not for now)
    def _run_calculation(self, task: SaptTask) -> Dict[str, Any]:
        pass

    def _parse_output(self, output: Dict[str, Any], task: SaptTask) -> SaptResult:
        pass


# --- Tests for run_adaptive ---


def test_run_adaptive_converges():
    """Test adaptive workflow reaching convergence before max_rung."""
    # Define mock results simulating convergence at aug-cc-pVDZ (rung 1)
    mock_energies = {
        "jun-cc-pvdz": {"total": -10.0, "elst": -5.0},  # Rung 0
        "aug-cc-pvdz": {"total": -10.05, "elst": -4.98},  # Rung 1 (Converges)
        "jun-cc-pvtz": {"total": -10.06, "elst": -4.97},  # Rung 2 (Not reached)
    }
    # Define target accuracy where rung 1 should converge
    target_accuracy = {"sapt_total": 0.1, "elst": 0.05}  # ΔE = 0.05 <= 0.1, ΔE = 0.02 <= 0.05

    mock_backend = MockAdaptiveBackend(results_by_basis=mock_energies)
    adaptive_options = {"target_accuracy": target_accuracy, "max_rung": 3}  # Allow up to rung 3

    # Initial task starts at the lowest rung (or basis can be specified)
    start_task = SaptTask(
        id="converge_test", monomer_a=mol_a, monomer_b=mol_b, basis_set=BASIS_LADDER[0]
    )

    workflow = AdaptiveWorkflow(
        tasks=[start_task],
        backend_name="mock",  # Use mock backend
        adaptive_options=adaptive_options,
    )
    # Inject the mock backend instance AFTER initialization uses get_default_backend
    workflow.backend = mock_backend

    results = workflow.run_adaptive()

    # Check that we got exactly one result keyed by the original task ID
    assert len(results) == 1
    assert start_task.id in results  # Check for original task ID
    final_result = results[start_task.id]
    assert final_result is not None
    assert final_result.success
    # Verify it's the result from the *converged* rung (rung 1)
    assert final_result.energies == mock_energies["aug-cc-pvdz"]
    # Check the internal rung results dict (optional, for debugging)
    assert len(workflow.results_by_rung) == 2  # Ran rung 0 and 1
    assert workflow.results_by_rung[0].task_id == f"{start_task.id}_rung0"
    assert workflow.results_by_rung[1].task_id == f"{start_task.id}_rung1"


def test_run_adaptive_reaches_max_rung():
    """Test adaptive workflow reaching max_rung without convergence."""
    # Define mock results simulating non-convergence up to max_rung
    mock_energies = {
        "jun-cc-pvdz": {"total": -10.0},  # Rung 0
        "aug-cc-pvdz": {"total": -10.5},  # Rung 1
        "jun-cc-pvtz": {"total": -10.9},  # Rung 2 (Max)
    }
    target_accuracy = {"sapt_total": 0.1}  # Never converges with these energies
    mock_backend = MockAdaptiveBackend(results_by_basis=mock_energies)
    adaptive_options = {"target_accuracy": target_accuracy, "max_rung": 2}  # Max out at rung 2

    start_task = SaptTask(
        id="max_rung_test", monomer_a=mol_a, monomer_b=mol_b, basis_set=BASIS_LADDER[0]
    )

    workflow = AdaptiveWorkflow(
        tasks=[start_task],
        backend_name="mock",
        adaptive_options=adaptive_options,
    )
    workflow.backend = mock_backend

    results = workflow.run_adaptive()

    # Check results: Should contain results for all rungs run (0, 1, 2)
    # Keys should be rung-specific task IDs because it didn't converge
    expected_keys = {f"{start_task.id}_rung{i}" for i in range(adaptive_options["max_rung"] + 1)}
    assert set(results.keys()) == expected_keys
    assert len(results) == adaptive_options["max_rung"] + 1  # Rungs 0, 1, 2

    # Verify the final result corresponds to the max rung
    max_rung_idx = adaptive_options["max_rung"]
    final_rung_result = results[f"{start_task.id}_rung{max_rung_idx}"]
    assert final_rung_result.success
    # Check energy keys were simplified
    assert final_rung_result.energies == {"total": mock_energies["jun-cc-pvtz"]["total"]}
    assert len(workflow.results_by_rung) == max_rung_idx + 1  # Rungs 0, 1, 2 run


def test_run_adaptive_fails_midway():
    """Test adaptive workflow handling a failure during a rung."""
    mock_energies = {
        "jun-cc-pvdz": {"total": -10.0},  # Rung 0 (Success)
        # Rung 1 will be configured to fail in the mock backend
    }
    target_accuracy = {"sapt_total": 0.1}
    # Configure mock to fail for the second basis set (Rung 1)
    basis_to_fail = BASIS_LADDER[1]
    mock_backend = MockAdaptiveBackend(results_by_basis=mock_energies, fail_on_basis=basis_to_fail)
    adaptive_options = {"target_accuracy": target_accuracy, "max_rung": 3}

    start_task = SaptTask(
        id="fail_test", monomer_a=mol_a, monomer_b=mol_b, basis_set=BASIS_LADDER[0]
    )

    workflow = AdaptiveWorkflow(
        tasks=[start_task],
        backend_name="mock",
        adaptive_options=adaptive_options,
    )
    workflow.backend = mock_backend

    results = workflow.run_adaptive()

    # Check results: Should contain results for rungs attempted (0 success, 1 failure)
    # Keys should be rung-specific task IDs
    expected_keys = {f"{start_task.id}_rung0", f"{start_task.id}_rung1"}
    assert set(results.keys()) == expected_keys
    assert len(results) == 2

    # Verify rung 0 was successful
    rung0_result = results[f"{start_task.id}_rung0"]
    assert rung0_result.success
    assert rung0_result.energies == {"total": mock_energies["jun-cc-pvdz"]["total"]}

    # Verify rung 1 failed
    rung1_result = results[f"{start_task.id}_rung1"]
    assert not rung1_result.success
    assert f"Simulated failure for basis {basis_to_fail}" in rung1_result.error_message
    assert len(workflow.results_by_rung) == 2  # Rungs 0, 1 attempted


def test_run_adaptive_start_from_higher_rung():
    """Test adaptive workflow starting from a basis higher in the ladder."""
    mock_energies = {
        # Rung 0 (jun-cc-pvdz) - Should not be run
        "aug-cc-pvdz": {"total": -10.0, "elst": -5.0},  # Rung 1 (Start)
        "jun-cc-pvtz": {"total": -10.05, "elst": -4.98},  # Rung 2 (Converges)
        "aug-cc-pvtz": {"total": -10.06, "elst": -4.97},  # Rung 3 (Not reached)
    }
    target_accuracy = {"sapt_total": 0.1, "elst": 0.05}  # Converges at rung 2
    mock_backend = MockAdaptiveBackend(results_by_basis=mock_energies)
    adaptive_options = {"target_accuracy": target_accuracy, "max_rung": 3}

    # Start task from Rung 1
    start_basis = BASIS_LADDER[1]  # aug-cc-pvdz
    start_task = SaptTask(
        id="higher_start_test", monomer_a=mol_a, monomer_b=mol_b, basis_set=start_basis
    )

    workflow = AdaptiveWorkflow(
        tasks=[start_task],
        backend_name="mock",  # Use mock backend
        adaptive_options=adaptive_options,
    )
    workflow.backend = mock_backend

    results = workflow.run_adaptive()

    # Check converged result: Keyed by original task ID
    assert len(results) == 1
    assert start_task.id in results
    final_result = results[start_task.id]
    assert final_result is not None
    assert final_result.success
    # Verify convergence occurred at the expected rung (rung 2)
    assert final_result.task_id == f"{start_task.id}_rung2"  # ID reflects final rung
    # Check the energies match the converged rung's mock data
    assert final_result.energies == mock_energies["jun-cc-pvtz"]  # jun-cc-pvtz
    # Check internal state: Should have run rungs 1 and 2
    assert len(workflow.results_by_rung) == 2
    assert 0 not in workflow.results_by_rung  # Rung 0 should not have run
    assert 1 in workflow.results_by_rung
    assert 2 in workflow.results_by_rung
    assert workflow.results_by_rung[1].task_id == f"{start_task.id}_rung1"
    assert workflow.results_by_rung[2].task_id == f"{start_task.id}_rung2"


# --- Integration-Style Test using Convenience Function ---


def test_integration_adaptive_workflow(monkeypatch):
    """Integration test using run_adaptive_workflow and mock backend."""
    # Mock results simulating convergence at rung 2 (jun-cc-pvtz)
    mock_energies = {
        "jun-cc-pvdz": {"total": -10.0, "elst": -5.0},
        "aug-cc-pvdz": {"total": -10.5, "elst": -4.9},  # Delta E = 0.5 > 0.1, Elst = 0.1 > 0.05
        "jun-cc-pvtz": {
            "total": -10.55,
            "elst": -4.88,
        },  # Delta E = 0.05 <= 0.1, Elst = 0.02 <= 0.05 -> Converges
        "aug-cc-pvtz": {"total": -10.56, "elst": -4.87},
    }
    target_accuracy = {"sapt_total": 0.1, "elst": 0.05}
    adaptive_options = {"target_accuracy": target_accuracy, "max_rung": 3}
    mock_backend_instance = MockAdaptiveBackend(results_by_basis=mock_energies)

    # Mock the MockBackend constructor where get_backend('mock') will find it
    def mock_backend_constructor(*args, **kwargs):
        # This will be called when get_backend('mock') executes 'return MockBackend()'
        return mock_backend_instance

    # Patch the MockBackend class where get_backend imports it from
    monkeypatch.setattr("saptase.core.orchestrator.MockBackend", mock_backend_constructor)

    # Task starting at the lowest rung
    start_task = SaptTask(
        id="integration_test", monomer_a=mol_a, monomer_b=mol_b, basis_set=BASIS_LADDER[0]
    )

    # Run the workflow using the convenience function
    results = run_adaptive_workflow(
        tasks=[start_task],
        backend_name="mock",  # This will trigger the use of orchestrator.MockBackend
        adaptive_options=adaptive_options,
    )

    # Assertions:
    # 1. Converged, so result is keyed by original task ID
    assert len(results) == 1
    assert start_task.id in results
    final_result = results[start_task.id]
    assert final_result is not None
    assert final_result.success

    # 2. Convergence occurred at the expected rung (rung 2)
    assert final_result.task_id == f"{start_task.id}_rung2"  # ID reflects final rung
    # Check the energies match the converged rung's mock data
    assert final_result.energies == mock_energies["jun-cc-pvtz"]

    # 3. Check mock backend call history (optional)
    assert mock_backend_instance.call_history == [
        BASIS_LADDER[0],  # jun-cc-pvdz
        BASIS_LADDER[1],  # aug-cc-pvdz
        BASIS_LADDER[2],  # jun-cc-pvtz (converged)
    ]


# --- Tests for _check_convergence ---


@pytest.mark.parametrize(
    "prev_energies, curr_energies, target_accuracy, expected_converged, expected_reasons_contain",
    [
        # Case 1: All components converge
        (
            {"total": -10.0, "elst": -5.0, "exch": -2.0, "ind": -1.0, "disp": -2.0},
            {"total": -10.05, "elst": -4.98, "exch": -2.01, "ind": -1.01, "disp": -2.05},
            {"sapt_total": 0.1, "elst": 0.05, "exch": 0.05, "ind": 0.05, "disp": 0.1},
            True,
            {
                "sapt_total": "Converged",
                "elst": "Converged",
                "exch": "Converged",
                "ind": "Converged",
                "disp": "Converged",
            },
        ),
        # Case 2: One component does NOT converge
        (
            {"total": -10.0, "elst": -5.0},
            {"total": -10.05, "elst": -4.90},  # elst difference 0.1 > 0.05
            {"sapt_total": 0.1, "elst": 0.05},
            False,
            {"sapt_total": "Converged", "elst": "NOT Converged"},
        ),
        # Case 3: Missing component in target_accuracy -> ignored
        (
            {"total": -10.0, "elst": -5.0, "ignored_comp": 1.0},
            {"total": -10.05, "elst": -4.98, "ignored_comp": 1.1},
            {"sapt_total": 0.1, "elst": 0.05},  # ignored_comp not checked
            True,
            {"sapt_total": "Converged", "elst": "Converged"},
        ),
        # Case 4: Missing energy component in results -> No convergence for that key
        (
            {"total": -10.0},  # Missing elst
            {"total": -10.05, "elst": -4.98},
            {"sapt_total": 0.1, "elst": 0.05},
            False,  # Expect False because 'elst' is required but missing in prev
            {"sapt_total": "Converged", "elst": "missing in one or both rungs"},
        ),
        # Case 5: Target accuracy key doesn't map to results -> No convergence
        (
            {"total": -10.0, "elst": -5.0},
            {"total": -10.05, "elst": -4.98},
            {"sapt_total": 0.1, "non_existent_key": 0.01},
            True,  # Expect True because unmapped keys are ignored, and 'total' converges
            {"sapt_total": "Converged", "non_existent_key": "key 'non_existent_key' not found"},
        ),
        # Case 6: Empty target accuracy -> No convergence
        (
            {"total": -10.0},
            {"total": -10.05},
            {},  # No tolerances
            False,
            {},  # No reasons generated if target_accuracy is empty
        ),
        # Case 7: Empty energies -> No convergence
        (
            {},
            {"total": -10.05},
            {"sapt_total": 0.1},
            False,
            {"error": "Missing energy components"},  # Specific error reason
        ),
    ],
)
def test_check_convergence(
    prev_energies: Dict[str, float],
    curr_energies: Dict[str, float],
    target_accuracy: Dict[str, float],
    expected_converged: bool,
    expected_reasons_contain: Dict[str, str],
):
    """Tests the _check_convergence logic with various scenarios."""
    # Create an AdaptiveWorkflow instance with the specified accuracy
    # Backend doesn't matter for this unit test
    # Use dummy_task which has basis_set defined
    
    # Patch get_backend for the scope of this test
    with patch('saptase.workflows.adaptive.get_backend') as mock_get_backend:
        mock_backend_instance = MagicMock(spec=SaptBackend)
        mock_get_backend.return_value = mock_backend_instance

        workflow = AdaptiveWorkflow(
            tasks=[dummy_task], adaptive_options={"target_accuracy": target_accuracy}
        )

    # Test the private _check_convergence method
    # Ensure energies are present in results, as _check_convergence expects them
    prev_result = create_dummy_result("task_rung0", prev_energies)
    curr_result = create_dummy_result("task_rung1", curr_energies)

    converged, reasons = workflow._check_convergence(prev_result, curr_result)

    assert converged == expected_converged

    if not target_accuracy and not prev_energies:  # Specific check for case 7
        assert reasons == expected_reasons_contain
    else:
        # Check if the generated reasons contain the expected substrings
        assert len(reasons) == len(expected_reasons_contain)
        for key, expected_substring in expected_reasons_contain.items():
            assert key in reasons
            assert expected_substring in reasons[key]

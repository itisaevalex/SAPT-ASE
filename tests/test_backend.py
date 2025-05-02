from unittest.mock import MagicMock, call, patch

import pytest

# Make sure psi4 can be imported or mock it entirely if needed
try:
    import psi4

    PSI4_CONVERGENCE_ERROR = psi4.SCFConvergenceError
except ImportError:
    # If psi4 is not installed in the test environment, create a mock exception
    class MockPsi4SCFConvergenceError(Exception):
        pass

    PSI4_CONVERGENCE_ERROR = MockPsi4SCFConvergenceError
    psi4 = MagicMock()
    psi4.SCFConvergenceError = PSI4_CONVERGENCE_ERROR

from saptase.core.backend import Psi4Backend, get_backend
from saptase.core.models import Molecule, SaptTask, TaskStatus


@pytest.fixture
def psi4_backend() -> Psi4Backend:
    """Fixture to create a Psi4Backend instance."""
    # Use the factory function for consistency
    return get_backend("psi4", options={"memory": "1GB"})  # type: ignore


@pytest.fixture
def sample_task() -> SaptTask:
    """Fixture for a sample SaptTask."""
    mol_a = Molecule(symbols=["H"], coordinates=[[0, 0, 0]])
    mol_b = Molecule(symbols=["H"], coordinates=[[0, 0, 1]])
    return SaptTask(
        id="test_task",
        monomer_a=mol_a,
        monomer_b=mol_b,
        method="sapt0",
        basis_set="sto-3g",
        additional_keywords={"user_scf_opt": "user_val"},
    )


# --- Test Cases will go here --- #


@pytest.mark.psi4
def test_psi4_backend_init(psi4_backend):
    """Test basic initialization of Psi4Backend."""
    assert isinstance(psi4_backend, Psi4Backend)
    assert psi4_backend.memory == "1GB"


@pytest.mark.psi4
@patch("saptase.core.backend.psi4", autospec=True)
def test_psi4_scf_recovery_success_on_second_attempt(mock_psi4, psi4_backend, sample_task):
    """Test that calculation recovers and succeeds on the 2nd SCF attempt."""
    # --- Mock Psi4 behavior --- #
    # 1. Mock energy to fail first time, succeed second time
    mock_psi4.SCFConvergenceError = PSI4_CONVERGENCE_ERROR  # Ensure mock psi4 has the error
    mock_psi4.energy.side_effect = [
        PSI4_CONVERGENCE_ERROR(
            "SCF failed on attempt 1", 99, MagicMock(), 1e-5, 1e-5
        ),  # Fails first call
        None,  # Succeeds second call (psi4.energy returns None on success)
    ]

    # 2. Mock variable to return dummy energies after success
    mock_psi4.variable.side_effect = lambda key: {
        "SAPT TOTAL ENERGY": -0.1,
        "SAPT ELST ENERGY": -0.2,
        "SAPT EXCH ENERGY": 0.15,
        "SAPT IND ENERGY": -0.05,
        "SAPT DISP ENERGY": -0.08,
    }.get(
        key, 0.0
    )  # Default to 0.0 if key not found

    # --- Run the calculation --- #
    result = psi4_backend.calculate(sample_task)

    # --- Assertions --- #
    assert result.success is True
    assert sample_task.status == TaskStatus.COMPLETED
    assert result.error_message is None

    # Check energies were extracted
    assert result.energies["total"] == -0.1
    assert result.energies["exchange"] == 0.15

    # Check psi4 calls
    assert mock_psi4.energy.call_count == 2
    assert mock_psi4.variable.call_count == 5  # Called for each energy component
    assert mock_psi4.set_options.call_count == 2

    # Check options passed in each attempt
    expected_options_attempt_1 = {
        "basis": "sto-3g",
        "scf_type": "df",
        "freeze_core": "true",
        "user_scf_opt": "user_val",  # From task
        # ... plus defaults from ladder attempt 0 (empty dict)
    }
    expected_options_attempt_2 = {
        "basis": "sto-3g",
        "scf_type": "df",
        "freeze_core": "true",
        "user_scf_opt": "user_val",  # From task
        "maxiter": 100,  # From ladder attempt 1
    }

    call_args_list = mock_psi4.set_options.call_args_list
    assert call_args_list[0] == call(expected_options_attempt_1)
    assert call_args_list[1] == call(expected_options_attempt_2)


# --- More Test Cases --- #


@pytest.mark.psi4
@patch("saptase.core.backend.psi4", autospec=True)
def test_psi4_scf_success_first_attempt(mock_psi4, psi4_backend, sample_task):
    """Test calculation succeeds on the first SCF attempt without recovery."""
    # Mock energy to succeed immediately
    mock_psi4.energy.side_effect = [None]
    # Mock variable calls
    mock_psi4.variable.return_value = -0.1  # Simple mock for all energy keys

    result = psi4_backend.calculate(sample_task)

    assert result.success is True
    assert sample_task.status == TaskStatus.COMPLETED
    assert mock_psi4.energy.call_count == 1
    assert mock_psi4.set_options.call_count == 1
    # Check the options were the initial defaults + task keywords
    expected_options = {
        "basis": "sto-3g",
        "scf_type": "df",
        "freeze_core": "true",
        "user_scf_opt": "user_val",
    }
    mock_psi4.set_options.assert_called_once_with(expected_options)
    assert result.energies["total"] == -0.1


@pytest.mark.psi4
@patch("saptase.core.backend.psi4", autospec=True)
def test_psi4_scf_failure_all_attempts(mock_psi4, psi4_backend, sample_task):
    """Test calculation fails after exhausting all SCF recovery attempts."""
    # Mock energy to always fail
    num_attempts = len(psi4_backend.SCF_RECOVERY_LADDER)
    mock_psi4.SCFConvergenceError = PSI4_CONVERGENCE_ERROR
    mock_psi4.energy.side_effect = [
        PSI4_CONVERGENCE_ERROR(f"SCF failed on attempt {i+1}", 99, MagicMock(), 1e-5, 1e-5)
        for i in range(num_attempts)
    ]

    result = psi4_backend.calculate(sample_task)

    assert result.success is False
    assert sample_task.status == TaskStatus.FAILED
    assert mock_psi4.energy.call_count == num_attempts
    assert mock_psi4.set_options.call_count == num_attempts
    assert "SCF failed to converge after" in result.error_message
    # Check that the string representation of the actual caught Psi4 exception is included
    assert (
        "Last error: Could not converge SCF failed on attempt 4 in 99 iterations."
        in result.error_message
    )

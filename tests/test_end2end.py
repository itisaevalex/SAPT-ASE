"""End-to-end tests for SAPTASE."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from saptase.core.backend import Psi4Backend
from saptase.core.models import Molecule, SaptResult, SaptTask, TaskStatus
from saptase.core.orchestrator import SaptWorkflow, run_sapt

# Water dimer geometry (from S22 benchmark set)
WATER_DIMER_A = """3
Water monomer A
O        -1.551007    -0.114520     0.000000
H        -1.934259     0.762503     0.000000
H        -0.599677     0.040712     0.000000
"""

WATER_DIMER_B = """3
Water monomer B
O         1.350625     0.111469     0.000000
H         1.680398    -0.373741    -0.758561
H         1.680398    -0.373741     0.758561
"""

# Reference value for SAPT0/jun-cc-pVDZ water dimer interaction energy (in Hartree)
# This is an approximate value for testing - actual value depends on exact geometry and Psi4 version
WATER_DIMER_REFERENCE_ENERGY = -0.007525  # ~-4.72 kcal/mol


# Create a fixture for water dimer molecules
@pytest.fixture
def water_dimer():
    """Create water dimer molecules for testing."""
    monomer_a = Molecule.from_xyz_string(WATER_DIMER_A)
    monomer_b = Molecule.from_xyz_string(WATER_DIMER_B)
    return monomer_a, monomer_b


# Check if Psi4 is available
try:
    # We don't actually need to import psi4 here, just check if it's importable
    # import psi4
    import importlib.util
    if importlib.util.find_spec("psi4") is None:
        raise ImportError
    PSI4_AVAILABLE = True
except ImportError:
    PSI4_AVAILABLE = False


# Skip tests that require Psi4 if it's not available
requires_psi4 = pytest.mark.skipif(
    not PSI4_AVAILABLE, reason="Psi4 is not available, skipping tests that require it"
)


# Test Molecule creation from XYZ string
def test_molecule_from_xyz():
    """Test creation of Molecule from XYZ string."""
    mol = Molecule.from_xyz_string(WATER_DIMER_A)

    assert len(mol.symbols) == 3
    assert mol.symbols == ["O", "H", "H"]
    assert mol.coordinates.shape == (3, 3)
    assert mol.name == "Water monomer A"
    assert mol.charge == 0
    assert mol.multiplicity == 1


# Test SaptTask creation
def test_sapt_task_creation(water_dimer):
    """Test creation of a SaptTask."""
    monomer_a, monomer_b = water_dimer

    task = SaptTask(
        monomer_a=monomer_a, monomer_b=monomer_b, basis_set="jun-cc-pVDZ", method="sapt0"
    )

    assert task.monomer_a is monomer_a
    assert task.monomer_b is monomer_b
    assert task.basis_set == "jun-cc-pVDZ"
    assert task.method == "sapt0"
    assert task.status == TaskStatus.PENDING
    assert task.id is not None  # Should generate an ID


# Test SaptWorkflow functionality
def test_workflow_add_task(water_dimer):
    """Test adding tasks to a SaptWorkflow."""
    monomer_a, monomer_b = water_dimer

    workflow = SaptWorkflow()
    task = SaptTask(monomer_a=monomer_a, monomer_b=monomer_b)

    workflow.add_task(task)
    assert len(workflow.tasks) == 1
    assert workflow.tasks[0] is task

    # Test add_dimer helper
    task2 = workflow.add_dimer(monomer_a, monomer_b, basis_set="aug-cc-pVDZ")
    assert len(workflow.tasks) == 2
    assert task2.basis_set == "aug-cc-pVDZ"


# Mock a successful Psi4 calculation for testing without Psi4
def mock_psi4_calculate(task):
    """Mock a successful Psi4 calculation."""
    result = SaptResult(task_id=task.id)
    result.success = True
    result.energies = {
        "total": WATER_DIMER_REFERENCE_ENERGY,
        "electrostatics": -0.012345,
        "exchange": 0.007890,
        "induction": -0.001234,
        "dispersion": -0.001836,
    }
    task.status = TaskStatus.COMPLETED
    return result


# Test run_local_serial with mocked backend
def test_workflow_run_local_serial(water_dimer):
    """Test running a SaptWorkflow with a mocked backend."""
    monomer_a, monomer_b = water_dimer

    # Create a mock backend
    mock_backend = MagicMock()
    mock_backend.calculate.side_effect = mock_psi4_calculate

    # Create a workflow with the mock backend
    workflow = SaptWorkflow(backend=mock_backend)
    task = workflow.add_dimer(monomer_a, monomer_b)

    # Run the workflow
    results = workflow.run_local_serial()

    # Check that the mock was called
    mock_backend.calculate.assert_called_once()

    # Check the results
    assert task.id in results
    assert results[task.id].success
    assert results[task.id].energies["total"] == WATER_DIMER_REFERENCE_ENERGY
    assert abs(results[task.id].total_energy - WATER_DIMER_REFERENCE_ENERGY) < 1e-10


# Test the convenience function
def test_run_sapt_convenience(water_dimer):
    """Test the run_sapt convenience function."""
    monomer_a, monomer_b = water_dimer

    # Create a mock backend
    mock_backend = MagicMock()
    mock_backend.calculate.side_effect = mock_psi4_calculate

    # Run the calculation
    result = run_sapt(monomer_a, monomer_b, backend=mock_backend)

    # Check the results
    assert result.success
    assert result.energies["total"] == WATER_DIMER_REFERENCE_ENERGY


# Only run this test if Psi4 is available
@requires_psi4
def test_real_psi4_water_dimer(water_dimer):
    """Test running a real SAPT calculation with Psi4."""
    monomer_a, monomer_b = water_dimer

    # Create a backend with more memory for real calculation
    backend = Psi4Backend(memory="500MB")

    # Run the calculation
    result = run_sapt(monomer_a, monomer_b, backend=backend)

    # Check the results
    assert result.success, f"SAPT calculation failed: {result.error_message}"
    assert "total" in result.energies

    # Check that the energy is close to the reference value
    # Be more lenient with the tolerance since the exact value might vary with Psi4 version
    assert abs(result.total_energy - WATER_DIMER_REFERENCE_ENERGY) < 0.001

    # Print the result for manual verification
    print(f"Water dimer SAPT0/jun-cc-pVDZ energy: {result.total_energy:.8f} Hartree")
    print(f"                                       {result.total_energy_kcal_mol():.4f} kcal/mol")


# Example script that can be run directly
if __name__ == "__main__":
    """Example script for running a water dimer SAPT calculation."""
    from saptase.core.models import Molecule
    from saptase.core.orchestrator import run_sapt

    # Create water molecules
    water_a = Molecule.from_xyz_string(WATER_DIMER_A)
    water_b = Molecule.from_xyz_string(WATER_DIMER_B)

    # Run SAPT calculation
    try:
        result = run_sapt(water_a, water_b, basis_set="jun-cc-pVDZ", method="sapt0")

        # Print results
        if result.success:
            print("SAPT calculation completed successfully!")
            print(f"Total interaction energy: {result.total_energy:.8f} Hartree")
            print(f"                          {result.total_energy_kcal_mol():.4f} kcal/mol")
            print("\nEnergy Components (Hartree):")
            for component, energy in result.energies.items():
                print(f"  {component.capitalize():13s}: {energy:.8f}")
        else:
            print(f"SAPT calculation failed: {result.error_message}")
    except Exception as e:
        print(f"Error running SAPT calculation: {e}")

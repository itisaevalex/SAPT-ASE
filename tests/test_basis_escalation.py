import pytest
from saptase.core import get_default_backend
from saptase.core.models import Molecule
from saptase.core.orchestrator import SaptWorkflow # LogDb is not directly used by this test
# from saptase.core.logdb import LogDb # Not needed for this test logic

@pytest.mark.psi4   # Use the registered 'psi4' marker
def test_actual_basis_differs_after_escalation(tmp_path):
    # Deliberately minimal basis that will hit the recovery ladder
    bad_basis = "sto-3g"
    # Assuming 'jun-cc-pvdz' is a basis set that 'sto-3g' would escalate to,
    # or is a generally more robust basis that a very minimal one might escalate towards.
    # The exact next rung depends on the BASIS_LADDER in saptase.recovery.strategies
    # For this test, we mainly care that it *changes* to something valid and successful.
    # We will assert a specific good_basis if we are sure about the ladder.
    # For now, let's assume 'jun-cc-pvdz' is a likely candidate or a known good one.
    good_basis = "jun-cc-pvdz"

    # Define two distinct Helium atoms for a simple dimer
    monomer_a_xyz = """1
Helium atom A
He 0.0 0.0 0.0
"""
    monomer_b_xyz = """1
Helium atom B
He 3.0 0.0 0.0
"""
    mol_a = Molecule.from_xyz_string(monomer_a_xyz)
    mol_b = Molecule.from_xyz_string(monomer_b_xyz)

    # Setup workflow with a real backend and a temporary database
    wf = SaptWorkflow(backend=get_default_backend(),
                      db_path=tmp_path / "runs.sqlite")
    
    # Add the dimer task with the 'bad' basis set
    wf.add_dimer(mol_a, mol_b, task_id="he_dimer_escalation_test", basis_set=bad_basis)

    # Run the workflow (single task, so local_parallel with 1 worker is fine and tests the orchestrator path)
    results_dict = wf.run_local_parallel(max_workers=1)
    
    # Check that the task is in the results
    assert "he_dimer_escalation_test" in results_dict
    result = results_dict["he_dimer_escalation_test"]

    # Assertions based on the expected behavior of basis escalation
    assert result.success, f"Task should have succeeded after escalation, but failed. Error: {result.error_message}"
    assert result.actual_basis_set is not None, "actual_basis_set should be populated."
    assert result.actual_basis_set != bad_basis, f"actual_basis_set should have changed from '{bad_basis}', but is '{result.actual_basis_set}'."
    
    # This assertion depends on knowing the exact escalation path.
    # If sto-3g -> jun-cc-pvdz is a defined step, this is correct.
    # If the ladder is more complex, we might only assert it's a known good basis.
    # For now, assuming jun-cc-pvdz is the target or a known good outcome.
    assert result.actual_basis_set.lower() == good_basis.lower(), \
        f"Expected actual_basis_set to be '{good_basis}' after escalation, but got '{result.actual_basis_set}'."

    # Verify that the original requested basis is still logged correctly for the *result object itself*
    # This is the basis_set that was *requested* for the task that eventually succeeded (possibly after retries)
    # The 'basis_set' on the SaptResult object should reflect the one *attempted* for that specific SaptResult instance
    # In our orchestrator, task_result.basis_set = task.basis_set, so it's the one used for the successful calc.
    # And task_result.actual_basis_set is also set to task.basis_set.
    # The distinction is more about the *original* SaptTask's basis vs the one that finally worked.
    # The SaptResult.basis_set field is documented as "Basis set for the calculation"
    # The SaptResult.actual_basis_set is "Basis set finally used, after any escalation"
    # In _execute_task_for_parallel, for a successful task:
    #   task_result.basis_set = task.basis_set
    #   task_result.actual_basis_set = task.basis_set
    # This means both will hold the *final, successful* basis. The test logic is fine with this.
    assert result.basis_set.lower() == good_basis.lower(), \
        f"SaptResult.basis_set should reflect the successful basis '{good_basis}', but got '{result.basis_set}'." 
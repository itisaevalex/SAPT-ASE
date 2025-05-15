import pytest
from pathlib import Path
import numpy as np

from saptase.core.models import Molecule, SaptResult, SaptTask
from saptase.core.orchestrator import SaptWorkflow, get_default_backend
from saptase.core.backend import SuccessMockBackend
from saptase.core.logdb import LogDb

# Define simple monomers for testing
monomer_a_xyz_str = "1\nHelium A\nHe 0.0 0.0 0.0"
monomer_b_xyz_str = "1\nHelium B\nHe 1.0 0.0 0.0"

mol_a = Molecule.from_xyz_string(monomer_a_xyz_str)
mol_b = Molecule.from_xyz_string(monomer_b_xyz_str)

@pytest.mark.fast
def test_cache_skip_with_mock_backend(tmp_path):
    """Test that a second identical run skips calculation due to cache hit,
    using a mock backend that simulates success.
    """
    db_path = tmp_path / "runs.sqlite"

    # Ensure get_default_backend() will return SuccessMockBackend for this test setup
    # This typically happens if CI_FAST is set, or if we patch it.
    # For simplicity, we'll assume CI_FAST or similar mechanism makes it use SuccessMockBackend.
    # Alternatively, explicitly pass SuccessMockBackend().
    backend_to_use = SuccessMockBackend() # Explicitly use the mock backend

    # --- First run (fills cache) ---
    wf1 = SaptWorkflow(backend=backend_to_use, db_path=db_path)
    task1 = wf1.add_dimer(mol_a, mol_b, task_id="t1_cache_test", basis_set="jun-cc-pvdz", method="sapt0")
    
    # Manually set monomer_xyz in task_result for mock backend as it doesn't run full orchestrator worker logic
    # In a real run, _execute_task_for_parallel populates these on SaptResult before logging.
    # For SuccessMockBackend, we need to ensure these are on the SaptResult that LogDB gets.
    # The LogDb.log_task_attempt expects them on the SaptResult object.
    # The orchestrator currently sets these *after* backend.calculate().
    # So, for the mock to populate the cache correctly, the SaptResult it returns needs them.
    # However, the cache *population* happens in LogDb based on the SaptResult it receives.
    # The cache *lookup* happens in the orchestrator based on the SaptTask.
    # Let's assume SuccessMockBackend will have these XYZ fields added directly or the orchestrator
    # will add them to the result before it hits LogDb (as it does now).

    results1 = wf1.run_local_parallel(max_workers=1)
    assert "t1_cache_test" in results1
    res1 = results1["t1_cache_test"]
    assert res1.success
    assert not getattr(res1, 'from_cache', False), "First run should not be from cache"

    # Verify that the result was actually cached by querying LogDb directly (optional check)
    logdb_check = LogDb(db_path)
    cached_check = logdb_check.get_cached_result(
        monomer_a_xyz=mol_a.to_xyz_string(),
        monomer_b_xyz=mol_b.to_xyz_string(),
        basis_set="jun-cc-pvdz",
        method="sapt0"
    )
    logdb_check.close()
    assert cached_check is not None, "Result should be in cache after first run"
    assert cached_check.task_id == "t1_cache_test" # The SaptResult from cache has original task_id

    # --- Second identical run (should skip) ---
    # For the second run, the orchestrator should find the result from wf1 in the cache.
    wf2 = SaptWorkflow(backend=backend_to_use, db_path=db_path)
    task2 = wf2.add_dimer(mol_a, mol_b, task_id="t2_cache_test", basis_set="jun-cc-pvdz", method="sapt0")
    results2 = wf2.run_local_parallel(max_workers=1)

    assert "t2_cache_test" in results2
    res2 = results2["t2_cache_test"]
    assert res2.success, f"Second run failed: {res2.error_message}"
    assert getattr(res2, 'from_cache', False), "Second run should be from cache"
    
    # The task_id of the result returned by the orchestrator for t2_cache_test should be t2_cache_test.
    # The underlying SaptResult object (if from_json worked) might have the original task_id
    # from when it was cached ('t1_cache_test'). This depends on how SaptResult.from_json handles fields.
    # The current SaptResult.from_json just passes **data, so it would reflect the cached SaptResult's task_id.
    # The orchestrator, when it gets a cache hit, should probably update the task_id of the returned
    # SaptResult to match the current task's ID if they differ, or ensure the comparison is okay.
    # For now, let's assume the orchestrator returns a result associated with 't2_cache_test'.
    # The critical part is that from_cache is True.
    assert res2.task_id == "t2_cache_test" # This is what run_local_parallel keys on.
    
    # If res2 is from cache, its energies should match res1's (or the cached_check's)
    assert res2.energies == res1.energies 
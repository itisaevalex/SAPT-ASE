import os
import time

import pytest
from dask.distributed import Client, LocalCluster
from saptase.core.models import Molecule, SaptTask
from saptase.execution.dask import DaskExecutor


@pytest.mark.dask
def test_dask_two_tasks_isolated_scratch(tmp_path):
    root = tmp_path / "scratch"
    os.environ["SAPTASE_SCRATCH_ROOT"] = str(root)

    mol = Molecule(symbols=["H"], coordinates=[[0, 0, 0]])
    t1 = SaptTask(monomer_a=mol, monomer_b=mol, id="t1")
    t2 = SaptTask(monomer_a=mol, monomer_b=mol, id="t2")

    # Let DaskExecutor manage the cluster creation and shutdown
    # scheduler=None tells it to create a LocalCluster
    with DaskExecutor(scheduler=None, n_workers=1) as ex:
        # The executor now owns the client and cluster
        ex.run_tasks([t1, t2])
    # DaskExecutor.__exit__ handles closing the client and the owned cluster

    # Add a small delay to allow Dask cleanup to fully complete before fixture check
    # time.sleep(5) # Removed - cleanup should now be handled reliably by DaskExecutor.close()

    # After completion scratch dirs should be cleaned (keep_scratch=False default)
    d1 = root / "saptase" / "t1"
    d2 = root / "saptase" / "t2"
    assert not d1.exists()
    assert not d2.exists()

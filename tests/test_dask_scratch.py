import os

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

    with LocalCluster(n_workers=1, threads_per_worker=1, asynchronous=False) as cluster:
        with Client(cluster) as client:
            ex = DaskExecutor(client)
            ex.run_tasks([t1, t2])

    # After completion scratch dirs should be cleaned (keep_scratch=False default)
    d1 = root / "saptase" / "t1"
    d2 = root / "saptase" / "t2"
    assert not d1.exists()
    assert not d2.exists()

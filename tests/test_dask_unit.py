"""Unit tests for the Dask execution path using a *pure‑Python* mock backend.

We deliberately avoid Psi4 here – only check orchestration + Dask wiring.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import socket
import pytest
from saptase.core.models import Molecule, SaptResult, SaptTask, TaskStatus
from saptase.core.orchestrator import SaptBackend, SaptWorkflow

try:
    import dask  # noqa: F401 (import just to check availability)
except ImportError:
    pytest.skip("dask.distributed not installed", allow_module_level=True)


@dataclass
class SleepyMockBackend(SaptBackend):
    """Mock backend that sleeps briefly and always succeeds."""

    sleep_time: float = 0.05

    def calculate(self, task: SaptTask) -> SaptResult:  # noqa: D401 (simple verb ok)
        import time

        time.sleep(self.sleep_time)
        res = SaptResult(task_id=task.id)
        res.success = True
        task.status = TaskStatus.COMPLETED
        return res


# Simple water monomers (coordinates irrelevant)
mon_a = Molecule(symbols=["H"], coordinates=[[0.0, 0.0, 0.0]])
mon_b = Molecule(symbols=["H"], coordinates=[[1.5, 0.0, 0.0]])


@pytest.mark.dask
def test_dask_execution_localcluster(tmp_path):
    """Submit 3 tasks to a LocalCluster and ensure they complete."""
    backend = SleepyMockBackend()
    wf = SaptWorkflow(backend=backend, db_path=tmp_path / "prov.sqlite")

    for i in range(3):
        wf.add_dimer(mon_a, mon_b, task_id=f"t{i}")

    results = wf.run_dask(max_workers=2)
    assert len(results) == 3
    assert all(r.success for r in results.values())
    assert all(t.status == TaskStatus.COMPLETED for t in wf.tasks)


scheduler_up = socket.socket().connect_ex(("localhost", 8786)) == 0


@pytest.mark.dask
@pytest.mark.skipif(not scheduler_up, reason="No scheduler running on :8786")
def test_dask_execution_external_scheduler(monkeypatch, tmp_path):
    """Pretend to connect to an external scheduler by monkey‑patching DaskExecutor."""

    # We replace DaskExecutor with a *fake* one that just calls ProcessPool underneath
    from saptase.execution import dask as dask_exec_mod

    class FakeExec:
        def __init__(self, scheduler=None, n_workers=None):  # noqa: D401
            from concurrent.futures import ProcessPoolExecutor

            self._executor = ProcessPoolExecutor(max_workers=n_workers or os.cpu_count())

        def submit_task(self, fn, *args):
            return self._executor.submit(fn, *args)

        def close(self):
            self._executor.shutdown()

    monkeypatch.setattr(dask_exec_mod, "DaskExecutor", FakeExec)

    backend = SleepyMockBackend()
    wf = SaptWorkflow(backend=backend, db_path=tmp_path / "prov.sqlite")
    wf.add_dimer(mon_a, mon_b, task_id="single")
    results = wf.run_dask(max_workers=1, scheduler="tcp://dummy:8786")
    assert results["single"].success

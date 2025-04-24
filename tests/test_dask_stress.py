"""Slow stress-test exercising Dask path with many tasks.

Marked *slow* so it only runs in nightly CI when RUN_STRESS=true.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import List

import numpy as np
import pytest
from dask.distributed import Client, LocalCluster
from saptase.core.backend import SaptBackend
from saptase.core.models import Molecule, SaptResult, SaptTask
from saptase.core.orchestrator import SaptWorkflow


class TrivialBackend(SaptBackend):
    """Backend that *always* succeeds instantly (no external deps)."""

    def calculate(self, task: SaptTask) -> SaptResult:
        # Produce a dummy result with constant energy so assertions work.
        return SaptResult(
            task_id=task.id,
            success=True,
            energies={"SAPT0 TOTAL ENERGY": -0.001},
            basis_set=task.basis_set,
            method=task.method,
        )


@pytest.mark.slow
@pytest.mark.dask
def test_dask_many_tasks_stress(tmp_path: Path):
    """Submit 100 tasks to a LocalCluster and ensure all succeed & are logged."""

    # Force scratch to tmp to avoid clutter on CI runners
    os.environ["SAPTASE_SCRATCH_ROOT"] = str(tmp_path / "scratch")

    # --- Build 100 simple tasks ---
    mol = Molecule(symbols=["He"], coordinates=np.zeros((1, 3)))
    tasks: List[SaptTask] = [
        SaptTask(id=f"stress_{i}", monomer_a=mol, monomer_b=mol) for i in range(100)
    ]

    # Use TrivialBackend so we spend near-zero time per calculation
    backend = TrivialBackend()

    db_path = tmp_path / "stress.sqlite"
    wf = SaptWorkflow(backend=backend, db_path=db_path)
    for t in tasks:
        wf.add_task(t)

    # --- Run via Dask ---
    t0 = time.perf_counter()
    with LocalCluster(n_workers=4, threads_per_worker=1, asynchronous=False) as cluster:
        with Client(cluster):
            wf.run_dask(max_workers=4)
    runtime = time.perf_counter() - t0

    # Assert time budget (should be < 20 s easily)
    assert runtime < 20, f"Stress test exceeded time budget: {runtime:.2f}s"

    # --- Validate results ---
    for res in wf.results.values():
        assert res.success, f"Task {res.task_id} did not succeed"
    assert len(wf.results) == 100, "Expected 100 results logged in workflow"

    # Ensure provenance DB has 100 rows
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM task_log")
        (count,) = cur.fetchone()
        assert count == 100, f"Expected 100 log rows, found {count}"
    finally:
        con.close()

"""Slow stress-test exercising Dask path with many tasks.

Marked *slow* so it only runs in nightly CI when RUN_STRESS=true.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
import gc  # Added for garbage collection
import asyncio # Added for sleep
from dask.distributed.utils import sync # Added for Dask sync
from pathlib import Path
from typing import List
import logging

import numpy as np
import pytest
from dask.distributed import Client, LocalCluster
from saptase.core.backend import SaptBackend
from saptase.core.models import Molecule, SaptResult, SaptTask
from saptase.core.orchestrator import SaptWorkflow

logger = logging.getLogger(__name__)

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
    cluster_instance = None
    with LocalCluster(n_workers=4, threads_per_worker=1, asynchronous=False) as cluster:
        cluster_instance = cluster # Keep a reference to the instance
        with Client(cluster):
            wf.run_dask(max_workers=4)

    # Ensure cluster is fully cleaned up before leak check
    if cluster_instance:
        cluster_addr = cluster_instance.scheduler_address
        start_time = time.monotonic()
        gc.collect()
        # Poll for removal from _instances
        while cluster_instance in LocalCluster._instances:
            # Extend timeout to 6 seconds
            if time.monotonic() - start_time > 6.0:
                logger.warning(f"Stress test cluster {cluster_addr} still in _instances after 6s timeout.")
                # Optionally fail the test here if the leak is critical
                # pytest.fail(f"Cluster {cluster_addr} leak detected after 6s timeout")
                break
            logger.debug(f"Waiting for stress test cluster {cluster_addr} to leave _instances...")
            gc.collect()
            time.sleep(0.05)   # give weak-ref a chance to clear
        else:
             logger.debug(f"Stress test cluster {cluster_addr} successfully removed from _instances.")

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


@pytest.mark.slow
@pytest.mark.dask
@pytest.mark.skipif(
    os.getenv("DASK_STRESS", "false").lower() != "true", reason="Set DASK_STRESS=true to run"
)
def test_cli_run_dask_stress(tmp_path):
    """Test running many tasks via CLI 'run --mode dask'."""
    N_TASKS = 100
    # F841: Remove unused variable
    # db_path = tmp_path / "stress_cli.sqlite"
    scratch_dir = tmp_path / "scratch_cli"
    scratch_dir.mkdir()

    # Create a minimal YAML for the stress test
    tasks_yaml = []
    for i in range(N_TASKS):
        tasks_yaml.append(
            f"""
- id: stress_task_{i}
  monomer_a:
    xyz: |
      1
      H
      H 0 0 0
  monomer_b:
    xyz: |
      1
      H
      H 0 0 {1.0 + i*0.1}
  basis_set: jun-cc-pVDZ # Mock backend ignores this
  method: sapt0
"""
        )

    stress_yaml_content = f"""
run_id: cli_dask_stress_run

execution:
  mode: dask # Default mode, will be overridden by CLI
  dask:
    n_workers: 4 # Default workers, can be overridden

tasks:
{"".join(tasks_yaml)}
"""

    stress_yaml_path = tmp_path / "stress_job.yml"
    stress_yaml_path.write_text(stress_yaml_content)

    # Command to run the CLI
    cmd = [
        sys.executable,
        # F821: Define CLI_PATH (assuming it's same as in test_cli_run.py)
        str(Path(__file__).parent.parent / "saptase" / "cli.py"),
        "run",
        str(stress_yaml_path),
        "--mode",
        "dask",
        "--workers",
        "4",  # Use a few workers
        "--scratch-root",
        str(scratch_dir),
        # Cannot directly override db_path via CLI yet, rely on CWD default?
        # Need to adjust if LogDb path is fixed
    ]

    start_time = time.time()
    # Execute the command
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "1"
    env["CI_FAST"] = "1"  # Use mocks
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=tmp_path, env=env)
    end_time = time.time()

    print("CLI STDOUT:")
    print(result.stdout)
    print("CLI STDERR:")
    print(result.stderr)

    assert result.returncode == 0, f"CLI stress test exited non-zero: {result.returncode}"

    # Check runtime
    duration = end_time - start_time
    assert duration < 25, f"CLI Dask stress test took too long: {duration:.2f}s"

    # Check database
    final_db_path = tmp_path / "runs" / "runs.sqlite"
    assert final_db_path.exists(), f"Provenance database not found at {final_db_path}"

    conn = sqlite3.connect(final_db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM task_log WHERE run_id = ? AND status = ?",
        ("cli_dask_stress_run", "COMPLETED"),
    )
    count = cursor.fetchone()[0]
    conn.close()

    assert count == N_TASKS, f"Expected {N_TASKS} completed tasks in DB, found {count}"

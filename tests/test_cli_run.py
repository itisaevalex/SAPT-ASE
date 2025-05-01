# tests/test_cli_run.py
"""Tests for the generic 'run' CLI subcommand."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

# Helper to get path to CLI script
CLI_PATH = Path(__file__).parent.parent / "saptase" / "cli.py"
EXAMPLE_YAML_PATH = Path(__file__).parent.parent / "examples" / "dask_local_demo.yml"


@pytest.mark.skipif(sys.platform == "win32", reason="Subprocess testing differences on Windows")
def test_cli_run_local_dask_success(tmp_path):
    """Test running the dask_local_demo via CLI 'run' command."""
    db_dir = tmp_path / "rundb"
    db_dir.mkdir()
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()

    # Command to run the CLI
    cmd = [
        sys.executable, # Use the same python interpreter running pytest
        str(CLI_PATH),
        "run",
        str(EXAMPLE_YAML_PATH),
        "--mode",
        "dask", # Explicitly test dask mode with local cluster
        "--workers",
        "1", # Keep it minimal for unit test
        # Override scratch root to use tmp_path for isolation
        "--scratch-root",
        str(scratch_dir),
    ]

    # Execute the command
    # Capture output and check exit code
    # Set OMP_NUM_THREADS=1 and CI_FAST=1 to ensure mocks are used if Psi4 is present
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "1"
    env["CI_FAST"] = "1"
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=tmp_path, env=env)

    print("CLI STDOUT:")
    print(result.stdout)
    print("CLI STDERR:")
    print(result.stderr)

    # Assertions
    assert result.returncode == 0, f"CLI exited with non-zero status: {result.returncode}"

    # Check database content
    # Inject DB path into workflow object instead?
    # For now, assume default relative path creation works
    # We need to know the *actual* DB path used by the run.
    # Let's assume it creates it in the CWD (tmp_path) for this test.
    # TODO: Make DB path more predictable or configurable for testing
    final_db_path = tmp_path / "runs" / "runs.sqlite"
    assert final_db_path.exists(), f"Provenance database not found at {final_db_path}"

    conn = sqlite3.connect(final_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT task_id, status FROM task_log WHERE run_id = ?", ("demo_dask_local_001",))
    rows = cursor.fetchall()
    conn.close()

    assert len(rows) == 2, f"Expected 2 rows in task_log, found {len(rows)}"
    assert rows[0][1] == "COMPLETED", f"Task {rows[0][0]} status was {rows[0][1]}, expected COMPLETED"
    assert rows[1][1] == "COMPLETED", f"Task {rows[1][0]} status was {rows[1][1]}, expected COMPLETED"

    # Check that scratch was created (presence of dirs like h_dimer_1*)
    scratch_contents = list(scratch_dir.iterdir())
    assert len(scratch_contents) > 0, "Scratch directory appears empty"
    assert any(d.name.startswith("h_dimer_1") for d in scratch_contents), "h_dimer_1 scratch missing"
    assert any(d.name.startswith("h_dimer_2") for d in scratch_contents), "h_dimer_2 scratch missing"

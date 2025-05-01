# tests/test_cli_run.py
"""Tests for the generic 'run' CLI subcommand."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

# Helper to get path to CLI script
# CLI_PATH is no longer needed for this test
# CLI_PATH = Path(__file__).parent.parent / "saptase" / "cli.py"
EXAMPLE_YAML_PATH = Path(__file__).parent.parent / "examples" / "dask_local_demo.yml"


# Remove the skipif marker to enable the test on Windows
# @pytest.mark.skipif(sys.platform == "win32", reason="Subprocess testing differences on Windows")
def test_cli_run_local_dask_success(tmp_path):
    """Test running the dask_local_demo via CLI 'run' command."""
    db_dir = tmp_path / "rundb"
    db_dir.mkdir()
    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()

    # Command to run the CLI
    # Use the entry point directly now
    cmd = [
        "saptase",  # Use the installed entry point
        "run",
        str(EXAMPLE_YAML_PATH),
        "--mode",
        "dask",  # Explicitly test dask mode with local cluster
        "--workers",
        "1",  # Keep it minimal for unit test
        # Override scratch root to use tmp_path for isolation
        "--scratch-root",
        str(scratch_dir),
        "--keep-scratch", # Add flag to prevent scratch cleanup
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
    final_db_path = tmp_path / "runs" / "runs.sqlite"
    assert final_db_path.exists(), f"Provenance database not found at {final_db_path}"

    conn = sqlite3.connect(final_db_path)
    cursor = conn.cursor()
    
    # Query status for the specific tasks by task_id
    cursor.execute(
        "SELECT status FROM task_log WHERE task_id = ? ORDER BY log_id DESC LIMIT 1", 
        ("h_dimer_1",)
    )
    row1 = cursor.fetchone()
    cursor.execute(
        "SELECT status FROM task_log WHERE task_id = ? ORDER BY log_id DESC LIMIT 1", 
        ("h_dimer_2",)
    )
    row2 = cursor.fetchone()
    conn.close()

    # Assert that both tasks were logged as COMPLETED
    assert row1 is not None, "Task h_dimer_1 not found in log"
    assert row1[0] == "COMPLETED", f"Task h_dimer_1 status was {row1[0]}, expected COMPLETED"
    assert row2 is not None, "Task h_dimer_2 not found in log"
    assert row2[0] == "COMPLETED", f"Task h_dimer_2 status was {row2[0]}, expected COMPLETED"

    # Check that scratch was created (presence of dirs like h_dimer_1*)
    # The actual task scratch dirs are created inside a 'saptase' subdir
    saptase_scratch_dir = scratch_dir / "saptase"
    assert saptase_scratch_dir.exists(), f"Expected 'saptase' scratch subdirectory not found in {scratch_dir}"
    
    scratch_contents = list(saptase_scratch_dir.iterdir())
    assert len(scratch_contents) > 0, f"Scratch subdirectory {saptase_scratch_dir} appears empty"
    assert any(
        d.name.startswith("h_dimer_1") for d in scratch_contents
    ), f"h_dimer_1 scratch missing in {saptase_scratch_dir}"
    assert any(
        d.name.startswith("h_dimer_2") for d in scratch_contents
    ), f"h_dimer_2 scratch missing in {saptase_scratch_dir}"

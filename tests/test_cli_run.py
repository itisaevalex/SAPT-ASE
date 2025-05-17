# tests/test_cli_run.py
"""Tests for the generic 'run' CLI subcommand."""

import os
import sqlite3
import subprocess
import sys  # Import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Helper to get path to CLI script
# CLI_PATH is no longer needed for this test
# CLI_PATH = Path(__file__).parent.parent / "saptase" / "cli.py"
EXAMPLE_YAML_PATH = Path(__file__).parent.parent / "examples" / "dask_local_demo.yml"


# Remove the skipif marker to enable the test on Windows
# @pytest.mark.skipif(sys.platform == "win32", reason="Subprocess testing differences on Windows")
@pytest.mark.dask
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
        "--keep-scratch",  # Add flag to prevent scratch cleanup
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
        "SELECT status FROM task_log WHERE task_id = ? ORDER BY log_id DESC LIMIT 1", ("h_dimer_1",)
    )
    row1 = cursor.fetchone()
    cursor.execute(
        "SELECT status FROM task_log WHERE task_id = ? ORDER BY log_id DESC LIMIT 1", ("h_dimer_2",)
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
    assert (
        saptase_scratch_dir.exists()
    ), f"Expected 'saptase' scratch subdirectory not found in {scratch_dir}"

    scratch_contents = list(saptase_scratch_dir.iterdir())
    assert len(scratch_contents) > 0, f"Scratch subdirectory {saptase_scratch_dir} appears empty"
    assert any(
        d.name.startswith("h_dimer_1") for d in scratch_contents
    ), f"h_dimer_1 scratch missing in {saptase_scratch_dir}"
    assert any(
        d.name.startswith("h_dimer_2") for d in scratch_contents
    ), f"h_dimer_2 scratch missing in {saptase_scratch_dir}"


@patch.dict(sys.modules, {"basis_set_exchange": MagicMock()})
@patch("saptase.cli.SaptWorkflow")
@patch("saptase.cli.load_config")
@patch("saptase.core.backend.get_backend")
@patch("saptase.hooks.basis_bootstrap.ensure_bases")
# @patch('saptase.hooks.basis_bootstrap.bse', MagicMock()) # This might no longer be needed or could be kept
def test_cli_run_db_path_propagation(
    mock_ensure_bases, mock_get_backend, mock_load_config, MockSaptWorkflow, tmp_path
):
    """Test that --db-path is correctly passed to SaptWorkflow via `saptase run`."""
    # Arrange
    custom_db_name = "custom_workflow.sqlite"
    custom_db_path = tmp_path / custom_db_name
    dummy_yaml_path = tmp_path / "dummy_sweep.yml"
    dummy_yaml_path.touch()  # Create a dummy yaml file

    # Mock load_config to return a minimal valid config structure
    mock_load_config.return_value = {
        "execution": {"backend": "psi4"},  # Minimal for backend selection
        "tasks": [
            {
                "id": "task1",
                "monomer_a": {"symbols": ["H"], "coordinates": [[0, 0, 0]]},
                "monomer_b": {"symbols": ["H"], "coordinates": [[0, 0, 1]]},
            }
        ],  # Need at least one task
    }

    # Mock SaptWorkflow instance to check calls to its methods (if needed later)
    mock_workflow_instance = MagicMock()
    MockSaptWorkflow.return_value = mock_workflow_instance
    # Mock methods of the instance if run_local_serial etc. are called and need specific returns
    mock_workflow_instance.run_local_serial.return_value = {}  # Example

    # Mock get_backend to return a MagicMock backend instance
    mock_backend_instance = MagicMock()
    mock_get_backend.return_value = mock_backend_instance

    # Act
    # Directly call the main function of the CLI module with arguments
    from saptase.cli import main as saptase_main

    saptase_main(
        [
            "run",
            str(dummy_yaml_path),
            "--db-path",
            str(custom_db_path),
            "--mode",
            "serial",  # Changed from "local_serial"
        ]
    )

    # Assert
    # Check that SaptWorkflow was instantiated with the correct db_path
    MockSaptWorkflow.assert_called_once()
    # The SaptWorkflow is called with backend and db_path as keyword arguments
    # or positional if the signature implies. Based on SaptWorkflow.__init__,
    # backend is positional or keyword, db_path is keyword.

    # Get the actual call arguments
    actual_call_args = MockSaptWorkflow.call_args
    # print(f"SAPTWORKFLOW_CALL_ARGS: {actual_call_args}") # Changed print content for clarity
    # print(f"SAPTWORKFLOW_MOCK_CALLS: {MockSaptWorkflow.mock_calls}") # Add this print

    # Expected: SaptWorkflow(backend=mock_backend_instance, db_path=Path(custom_db_path))
    assert actual_call_args is not None, "SaptWorkflow was not called"

    # Check keyword arguments specifically for db_path
    assert "db_path" in actual_call_args.kwargs, "db_path not in SaptWorkflow kwargs"
    assert Path(actual_call_args.kwargs["db_path"]) == Path(
        custom_db_path
    ), f"SaptWorkflow not called with correct db_path. Expected {custom_db_path}, got {actual_call_args.kwargs['db_path']}"

    # Ensure the mock_load_config was called with the dummy yaml path
    mock_load_config.assert_called_once_with(str(dummy_yaml_path))
    # Ensure the workflow execution method was called (example for local_serial)
    mock_workflow_instance.run_local_serial.assert_called_once()

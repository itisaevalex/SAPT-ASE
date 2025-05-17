"""Tests that back-ends respect TaskScratch isolation without real Psi4."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from saptase.core.backend import Psi4Backend
from saptase.core.models import Molecule, SaptResult, SaptTask
from saptase.core.scratch import TaskScratch


class DummyPsi4:  # minimal stub
    class core:
        @staticmethod
        def clean():
            pass

        @staticmethod
        def set_output_file(*args, **kwargs):
            pass

        @staticmethod
        def get_output_file_path():
            return str(Path(os.environ["PSI_SCRATCH"]) / "psi4_output.dat")

        @staticmethod
        def clean_variables():
            pass

        @staticmethod
        def clean_options():
            pass

    class SCFConvergenceError(RuntimeError):
        pass

    class ValidationError(RuntimeError):
        pass

    class BasisSetNotFound(RuntimeError):
        pass

    class PsiException(RuntimeError):
        pass

    @staticmethod
    def set_memory(*args, **kwargs):
        pass

    @staticmethod
    def set_options(*args, **kwargs):
        pass

    @staticmethod
    def geometry(mol):
        return None

    @staticmethod
    def energy(method, molecule=None):
        # Write sentinel into scratch dir
        sentinel = Path(os.environ["PSI_SCRATCH"]) / "sentinel.txt"
        sentinel.write_text("ok")
        return 0.0

    @staticmethod
    def variable(name):
        # Return fake energies
        return -0.1


@pytest.fixture(autouse=True)
def patch_psi4(monkeypatch):
    monkeypatch.setattr("saptase.core.backend.psi4", DummyPsi4, raising=False)


@pytest.mark.psi4
def test_backend_writes_in_scratch(tmp_path: Path):
    # Prepare molecules
    mol = Molecule(symbols=["H"], coordinates=[[0, 0, 0]])
    task = SaptTask(monomer_a=mol, monomer_b=mol, id="t1")

    root = tmp_path / "scratch"
    os.environ["SAPTASE_SCRATCH_ROOT"] = str(root)

    backend = Psi4Backend()
    with TaskScratch(task.id):
        res = backend.calculate(task)
        assert res.success is True
        sentinel = root / "saptase" / task.id / "sentinel.txt"
        assert sentinel.exists()

    # After outer context sentinel removed
    sentinel_path = root / "saptase" / task.id / "sentinel.txt"
    assert not sentinel_path.exists()


# Test cases for scratch_root and keep_scratch prioritization
# (task_keywords_scratch_root, task_keywords_keep_scratch,
#  backend_scratch_root, backend_keep_scratch,
#  env_scratch_root,
#  expected_effective_scratch_root_to_task_scratch, expected_effective_keep_scratch_to_task_scratch)
scratch_test_cases = [
    # Priority 1: Task keywords
    (
        "task_kw_scratch",
        True,
        "backend_scratch",
        False,
        None,
        "task_kw_scratch",
        True,
    ),  # Task overrides backend
    ("task_kw_scratch", False, "backend_scratch", True, None, "task_kw_scratch", False),
    (
        "task_kw_scratch",
        None,
        "backend_scratch",
        True,
        None,
        "task_kw_scratch",
        True,
    ),  # Task keep_scratch is None, uses task_scratch_root, backend keep_scratch
    (
        None,
        True,
        "backend_scratch",
        False,
        None,
        "backend_scratch",
        True,
    ),  # Task scratch_root is None, uses backend_scratch_root, task keep_scratch
    # Priority 2: Backend instance config (if task keyword is None)
    (
        None,
        None,
        "backend_scratch",
        True,
        "env_scratch",
        "backend_scratch",
        True,
    ),  # Backend overrides env if task kw are None
    (None, None, "backend_scratch", False, "env_scratch", "backend_scratch", False),
    # Priority 3: Environment variable SAPTASE_SCRATCH_ROOT (if task and backend are None for scratch_root)
    (
        None,
        None,
        None,
        True,
        "env_scratch",
        "env_scratch",
        True,
    ),  # Env scratch used, backend keep_scratch
    (None, None, None, False, "env_scratch", "env_scratch", False),
    (
        None,
        True,
        None,
        False,
        "env_scratch",
        "env_scratch",
        True,
    ),  # Env scratch used, task keep_scratch
    # Priority 4: TaskScratch defaults (if all others are None for scratch_root)
    (
        None,
        None,
        None,
        True,
        None,
        None,
        True,
    ),  # All None for root, TaskScratch uses its default. Backend keep_scratch
    (
        None,
        None,
        None,
        False,
        None,
        None,
        False,
    ),  # All None for root, TaskScratch uses its default. Backend keep_scratch
    (
        None,
        True,
        None,
        False,
        None,
        None,
        True,
    ),  # All None for root, TaskScratch uses its default. Task keep_scratch
]


@pytest.mark.parametrize(
    "task_kw_scratch_root, task_kw_keep_scratch, backend_scratch_root_config, backend_keep_scratch_config, env_saptase_scratch_root, expected_scratch_root, expected_keep_scratch",
    scratch_test_cases,
)
@patch("saptase.core.backend.TaskScratch")  # Mock TaskScratch to check its init args
@patch.object(Psi4Backend, "_calculate_inner")  # Mock the actual calculation part
@patch.object(Psi4Backend, "_has_psi4", return_value=True)  # Assume Psi4 is available
def test_psi4backend_scratch_prioritization(
    mock_has_psi4,
    mock_calculate_inner,
    MockTaskScratch,
    task_kw_scratch_root,
    task_kw_keep_scratch,
    backend_scratch_root_config,
    backend_keep_scratch_config,
    env_saptase_scratch_root,
    expected_scratch_root,
    expected_keep_scratch,
    tmp_path,
    monkeypatch,
):
    """Test the prioritization of scratch_root and keep_scratch settings in Psi4Backend."""
    # Arrange
    # Set environment variable if provided for the test case
    if env_saptase_scratch_root:
        monkeypatch.setenv("SAPTASE_SCRATCH_ROOT", str(tmp_path / env_saptase_scratch_root))
    else:
        monkeypatch.delenv("SAPTASE_SCRATCH_ROOT", raising=False)

    # Prepare backend instance
    # Convert relative path strings to absolute paths using tmp_path for backend config
    backend_abs_scratch_root = (
        tmp_path / backend_scratch_root_config if backend_scratch_root_config else None
    )
    backend = Psi4Backend(
        scratch_root=str(backend_abs_scratch_root) if backend_abs_scratch_root else None,
        keep_scratch=backend_keep_scratch_config,
    )

    # Prepare SaptTask with additional_keywords
    task_keywords = {}
    if task_kw_scratch_root:
        # Convert relative path strings to absolute paths for task keywords
        task_keywords["scratch_root"] = str(tmp_path / task_kw_scratch_root)
    if task_kw_keep_scratch is not None:
        task_keywords["keep_scratch"] = task_kw_keep_scratch

    mol = Molecule(symbols=["H"], coordinates=[[0, 0, 0]])
    task = SaptTask(
        monomer_a=mol, monomer_b=mol, id="t_scratch_prio", additional_keywords=task_keywords
    )

    # Mock TaskScratch to return a dummy path string from its context manager
    MockTaskScratch.return_value.__enter__.return_value = str(tmp_path / "dummy_managed_scratch")
    # Mock _calculate_inner to return a generic success SaptResult
    mock_calculate_inner.return_value = SaptResult(task_id=task.id, success=True)

    # Act
    backend.calculate(task)

    # Assert
    # Check that TaskScratch was initialized with the correctly prioritized arguments
    # Convert expected_scratch_root to absolute path if not None
    final_expected_scratch_root = (
        tmp_path / expected_scratch_root if expected_scratch_root else None
    )

    MockTaskScratch.assert_called_once_with(
        task.id,
        scratch_root=str(final_expected_scratch_root) if final_expected_scratch_root else None,
        keep_scratch=expected_keep_scratch,
    )
    mock_calculate_inner.assert_called_once_with(task, str(tmp_path / "dummy_managed_scratch"))

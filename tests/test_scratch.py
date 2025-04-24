"""Unit tests for TaskScratch context manager."""

from __future__ import annotations

import os
from pathlib import Path

from saptase.core.scratch import TaskScratch


def test_task_scratch_creates_and_cleans(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()

    os.environ["SAPTASE_SCRATCH_ROOT"] = str(root)

    task_id = "dummy"
    scratch_dir = root / "saptase" / task_id

    # Ensure directory does not exist yet
    assert not scratch_dir.exists()

    with TaskScratch(task_id) as p:
        assert Path(p) == scratch_dir
        assert scratch_dir.exists()
        # Env vars set
        assert os.environ["PSI_SCRATCH"] == str(scratch_dir)
        assert os.environ["PSI_TMPDIR"] == str(scratch_dir)

    # After context directory removed
    assert not scratch_dir.exists()
    # Variables restored/removed
    assert "PSI_SCRATCH" not in os.environ
    assert "PSI_TMPDIR" not in os.environ


def test_task_scratch_keep(tmp_path: Path):
    root = tmp_path / "root"
    os.environ["SAPTASE_SCRATCH_ROOT"] = str(root)

    task_id = "keepme"
    scratch_dir = root / "saptase" / task_id

    with TaskScratch(task_id, keep_scratch=True) as p:
        assert Path(p) == scratch_dir
        assert scratch_dir.exists()

    # Directory should persist
    assert scratch_dir.exists()

"""Tests that back-ends respect TaskScratch isolation without real Psi4."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from saptase.core.backend import Psi4Backend
from saptase.core.models import Molecule, SaptTask
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

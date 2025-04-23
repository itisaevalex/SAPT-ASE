"""Test fixtures and utilities for the saptase package."""

import logging

from saptase import SaptBackend, SaptResult, SaptTask, TaskStatus

logger = logging.getLogger(__name__)


class MockBackend(SaptBackend):
    """Mock backend for testing without Psi4."""

    def calculate(self, task: SaptTask) -> SaptResult:
        """Mock calculation that returns a dummy result.

        Args:
            task: The SAPT calculation task to perform

        Returns:
            A dummy SaptResult
        """
        # Create a dummy result
        result = SaptResult(task_id=task.id)
        result.success = True
        result.energies = {
            "total": -0.007525,  # Approx water dimer energy
            "electrostatics": -0.012345,
            "exchange": 0.007890,
            "induction": -0.001234,
            "dispersion": -0.001836,
        }
        task.status = TaskStatus.COMPLETED
        return result

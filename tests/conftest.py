"""Test fixtures and utilities for the saptase package."""

import logging
import pytest  # Added for fixture
from saptase import SaptBackend, SaptResult, SaptTask, TaskStatus

try: # Optional import for dask leak detection
    from distributed import LocalCluster
except ImportError:
    LocalCluster = None

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


# --- Dask Cluster Leak Detector Fixture ---
@pytest.fixture(autouse=True, scope="session")
def assert_no_leaked_dask_cluster():
    """Fixture to ensure no Dask LocalCluster instances are leaked across the session."""
    if LocalCluster is None:
        logger.debug("Dask not installed, skipping cluster leak check.")
        yield
        return

    # Record instances active *before* the session tests run
    # Use weakref set directly if LocalCluster._instances is not available/stable
    # For now, assume _instances exists as per the provided example
    try:
        before = set(LocalCluster._instances) # type: ignore
        logger.debug(f"Dask cluster instances before session: {len(before)}")
    except AttributeError:
        logger.warning("Could not access LocalCluster._instances, cannot perform leak check.")
        yield # Allow tests to run anyway
        return

    yield # Run the tests

    # Check instances remaining *after* the session tests
    try:
        after = set(LocalCluster._instances) # type: ignore
        logger.debug(f"Dask cluster instances after session: {len(after)}")
        leaked = after - before
        if leaked:
            # Construct a helpful error message
            leaked_details = []
            for cluster in leaked:
                try:
                    detail = f"Scheduler: {cluster.scheduler_address}, Dashboard: {cluster.dashboard_link}"
                except Exception:
                    detail = repr(cluster)
                leaked_details.append(detail)
            leaked_str = "; ".join(leaked_details)
            
            assert after <= before, (
                f"Leaked {len(leaked)} Dask LocalCluster(s): [{leaked_str}]. "
                "Ensure clusters/clients are closed, e.g., using 'with LocalCluster(...):' or 'client.close()'."
            )
        else:
             logger.debug("No Dask clusters appear to have been leaked during the session.")
    except AttributeError:
        # Logged warning on entry, nothing more to do
        pass
    except Exception as e:
        # Catch other potential errors during the check
        logger.error(f"Error during Dask leak check: {e}", exc_info=True)
        # Optionally re-raise or assert false here if errors during leak check should fail tests
        # pytest.fail(f"Error during Dask leak check: {e}")

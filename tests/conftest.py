import asyncio
import logging
import sys
import types  # Added for ModuleType

import pytest
from saptase import SaptBackend, SaptResult, SaptTask, TaskStatus

# --- Early Mocking for Psi4 components for _psi4_compat --- #
# This ensures that when saptase.core._psi4_compat is imported (e.g., by saptase.core.backend),
# it can find the mocked psi4.core.WavefunctionAlgorithmError if psi4 itself is not installed
# or if we are in a testing environment that intentionally mocks psi4.

# Ensure a mock psi4 module exists in sys.modules for tests that run without real Psi4
if "psi4" not in sys.modules:
    # Create a simple mock module object for 'psi4'
    mock_psi4_module = types.ModuleType("psi4")
    sys.modules["psi4"] = mock_psi4_module

# Ensure the mock psi4 module has a 'core' attribute, also a module
if not hasattr(sys.modules["psi4"], "core"):
    sys.modules["psi4"].core = types.ModuleType("psi4.core")

# Set the mock WavefunctionAlgorithmError on psi4.core
# This needs to be a class that can be instantiated and is an Exception subtype.
if not hasattr(sys.modules["psi4"].core, "WavefunctionAlgorithmError"):
    MockWavefunctionAlgorithmError = type("MockWavefunctionAlgorithmError", (Exception,), {})
    setattr(sys.modules["psi4"].core, "WavefunctionAlgorithmError", MockWavefunctionAlgorithmError)
    # Also make it available directly on mock psi4 module for other potential access patterns
    if not hasattr(sys.modules["psi4"], "WavefunctionAlgorithmError"):
        setattr(sys.modules["psi4"], "WavefunctionAlgorithmError", MockWavefunctionAlgorithmError)

# For other components that _psi4_compat might try to _first from psi4.core:
if not hasattr(sys.modules["psi4"].core, "BasisSetNotFound"):
    MockBasisSetNotFound = type("MockBasisSetNotFound", (Exception,), {})
    setattr(sys.modules["psi4"].core, "BasisSetNotFound", MockBasisSetNotFound)
    if not hasattr(sys.modules["psi4"], "BasisSetNotFound"):
        setattr(sys.modules["psi4"], "BasisSetNotFound", MockBasisSetNotFound)

if not hasattr(sys.modules["psi4"].core, "SCFConvergenceError"):
    MockSCFConvergenceError = type("MockSCFConvergenceError", (Exception,), {})
    setattr(sys.modules["psi4"].core, "SCFConvergenceError", MockSCFConvergenceError)
    if not hasattr(sys.modules["psi4"], "SCFConvergenceError"):
        setattr(sys.modules["psi4"], "SCFConvergenceError", MockSCFConvergenceError)

if not hasattr(sys.modules["psi4"].core, "Molecule"):
    # A simple mock class for Molecule might be enough if only type checking or basic attributes are needed.
    # If tests require specific methods or behaviors, this mock would need to be more sophisticated.
    class MockPsi4Molecule:
        def __init__(self, molecule_string=None):
            self.molecule_string = molecule_string

        # Add any methods that might be called by the code during tests if necessary
        # For example, if to_string() is called:
        # def to_string(self):
        #     return self.molecule_string or ""

    setattr(sys.modules["psi4"].core, "Molecule", MockPsi4Molecule)
    if not hasattr(sys.modules["psi4"], "Molecule"):
        setattr(sys.modules["psi4"], "Molecule", MockPsi4Molecule)

# --- End Early Mocking --- #


# Switch event loop policy on Windows for Dask compatibility
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        print(
            "\nINFO: Switched asyncio event loop policy to WindowsSelectorEventLoopPolicy for Dask tests.\n"
        )
    except Exception as e:
        print(f"\nWARNING: Failed to switch asyncio event loop policy: {e}\n")

"""Test fixtures and utilities for the saptase package."""

# Configure logging for tests
logging.basicConfig(level=logging.DEBUG, format="%(levelname)s:%(name)s:%(message)s")

try:  # Optional import for dask leak detection
    from distributed import LocalCluster
    from distributed.utils_test import cleanup as dask_cleanup_fixture  # Import with alias
except ImportError:
    LocalCluster = None
    dask_cleanup_fixture = None  # Define as None if import fails

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
        before = set(LocalCluster._instances)  # type: ignore
        logger.debug(f"Dask cluster instances before session: {len(before)}")
    except AttributeError:
        logger.warning("Could not access LocalCluster._instances, cannot perform leak check.")
        yield  # Allow tests to run anyway
        return

    yield  # Run the tests

    # Check instances remaining *after* the session tests
    try:
        after = set(LocalCluster._instances)  # type: ignore
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


@pytest.fixture(autouse=True)
def assert_no_cluster_leak_per_test():
    """Fixture to ensure no Dask LocalCluster is leaked by an individual test."""
    if LocalCluster is None:
        # Dask not installed, nothing to check
        yield
        return

    try:
        before = set(LocalCluster._instances)  # type: ignore
    except AttributeError:
        # This case should be caught by the session fixture's warning, but handle defensively
        logger.warning("Could not access LocalCluster._instances in per-test check.")
        yield
        return
    yield  # Run the actual test function

    try:
        after = set(LocalCluster._instances)  # type: ignore
        leaked = after - before
        if leaked:
            # Create a more informative message
            leaked_details = []
            for cluster in leaked:
                try:
                    # Attempt to get scheduler address, fall back if cluster is closed/inaccessible
                    scheduler_address = cluster.scheduler_address
                except Exception:
                    scheduler_address = "Cluster already closed or inaccessible"
                leaked_details.append(f"  - {cluster!r} (Scheduler: {scheduler_address})")

            pytest.fail(
                "Test leaked the following Dask LocalCluster instance(s):\\n"
                + "\\n".join(leaked_details)
                + "\\nEnsure the cluster is closed using a context manager or client.shutdown()."
            )
    except AttributeError:
        # Logged warning on entry, nothing more to do
        pass
    except Exception as e:
        # Catch other potential errors during the check
        logger.error(f"Error during per-test Dask leak check: {e}", exc_info=True)
        pytest.fail(f"Error during per-test Dask leak check: {e}")


# Make the dask cleanup fixture available for usefixtures
@pytest.fixture
def cleanup(request):
    """Yields the dask cleanup fixture if available."""
    if dask_cleanup_fixture is None:
        pytest.skip("Dask utils_test not available, skipping cleanup fixture.")
    # Dask's cleanup is a fixture function, so we call it
    # It might need the request object, let's pass it.
    # We don't actually need to *yield* anything from it here,
    # just ensure it runs by calling it.
    # The original cleanup fixture handles setup/teardown itself.
    # However, standard pytest fixtures expect a yield or return.
    # Let's yield it directly, assuming it behaves like a standard fixture.
    yield dask_cleanup_fixture

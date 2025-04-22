"""Backend implementations for SAPT calculations."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import logging

try:
    import psi4
except ImportError:
    psi4 = None  # Allow running the module without Psi4 installed

from .models import SaptResult, SaptTask, TaskStatus


class SaptBackend(ABC):
    """Abstract base class for SAPT calculation backends."""

    @abstractmethod
    def calculate(self, task: SaptTask) -> SaptResult:
        """Perform a SAPT calculation for the given task.

        Args:
            task: The SAPT calculation task to perform

        Returns:
            A SaptResult containing the calculation results
        """
        pass


# Backend Factory
def get_backend(
    backend_name: str, options: Optional[Dict[str, Any]] = None
) -> SaptBackend:
    """Factory function to get a SaptBackend instance.

    Args:
        backend_name: The name of the backend (case-insensitive).
        options: Dictionary of options for the backend constructor.

    Returns:
        An instance of the requested SaptBackend.

    Raises:
        ValueError: If the requested backend is not supported.
    """
    backend_name_lower = backend_name.lower()
    options = options or {}

    if backend_name_lower == "psi4":
        # Extract specific options if needed, e.g., memory
        psi4_memory = options.get("memory", "2GB")  # Default memory
        return Psi4Backend(memory=psi4_memory)
    elif backend_name_lower == "mock":
        # Import MockBackend locally to avoid circular dependency if MockBackend
        # itself needs to import things from backend.py, although currently it does not.
        # It's defined in orchestrator.py for now.
        try:
            # TODO: Consider moving MockBackend to core.backend or a testing module.
            from saptase.core.orchestrator import MockBackend
            # Mock backend might not take options, or we might pass them?
            # For now, assume it takes no options.
            return MockBackend()
        except ImportError:
            # This shouldn't happen if orchestrator exists, but good practice.
            raise ValueError("Mock backend requested but MockBackend class not found.")
    # Add elif clauses for CamCASP, SAPT2020 etc. when implemented
    # elif backend_name_lower == "camcasp":
    #     return CamCASPBackend(**options)
    else:
        raise ValueError(f"Unsupported backend: {backend_name}")


# --- Setup Logger --- #
logger = logging.getLogger(__name__)

# --- Backend Implementations ---


class Psi4Backend(SaptBackend):
    """Backend for SAPT calculations using Psi4.

    For MVP, this implements only single-threaded SAPT0 with jun-cc-pVDZ.
    """

    # --- Constants for Psi4Backend --- #
    SCF_RECOVERY_LADDER: List[Dict[str, Any]] = [
        # Attempt 1: Default settings (implicitly used if no keywords below are set)
        {},  # Psi4's defaults
        # Attempt 2: Increase max iterations
        {"maxiter": 100},
        # Attempt 3: Enable Second-Order SCF (SOSCF)
        {"soscf": "true", "maxiter": 150},
        # Attempt 4: DIIS + SOSCF with more iterations
        {"diis": "true", "soscf": "true", "maxiter": 200},
        # Attempt 5: Quadratic convergence (Note: often needs scf_type='pk')
        # We might need more logic if user specifies scf_type='df'
        # For now, let's only try this if defaults fail badly.
        # {"scf_type": "pk", "qc_scf": "true", "maxiter": 50}
    ]

    def __init__(self, memory: str = "2GB"):
        """Initialize the Psi4 backend.

        Args:
            memory: Memory allocation for Psi4
        """
        self.memory = memory

        if psi4 is None:
            raise ImportError("Psi4 is required for this backend but could not be imported")

    def calculate(self, task: SaptTask) -> SaptResult:
        """Perform a SAPT calculation using Psi4.

        Args:
            task: The SAPT calculation task to perform

        Returns:
            A SaptResult containing the calculation results
        """
        # Create a result object with the task ID
        result = SaptResult(task_id=task.id)

        try:
            # Update task status
            task.status = TaskStatus.RUNNING

            # Initialize Psi4
            psi4.core.clean()
            psi4.set_memory(self.memory)
            psi4.core.set_output_file("psi4_output.dat", False)

            # Create a dimer molecule with fragments
            a_xyz = task.monomer_a.to_xyz_string().split("\n", 2)[2]  # Skip atom count and comment
            b_xyz = task.monomer_b.to_xyz_string().split("\n", 2)[2]  # Skip atom count and comment

            # Format the molecule for Psi4 with fragment separation
            # Charge and multiplicity must be specified per fragment
            molecule_str = (
                f"{task.monomer_a.charge} {task.monomer_a.multiplicity}\n"
                f"{a_xyz}\n"
                f"--\n"
                f"{task.monomer_b.charge} {task.monomer_b.multiplicity}\n"
                f"{b_xyz}\n"
            )

            # Set up the Psi4 molecule
            psi4_mol = psi4.geometry(molecule_str)

            # --- SCF Recovery Loop --- #
            scf_success = False
            last_scf_error = None
            for attempt, scf_options in enumerate(self.SCF_RECOVERY_LADDER):
                logger.info(f"SCF Attempt {attempt + 1}/{len(self.SCF_RECOVERY_LADDER)} using options: {scf_options}")
                try:
                    # Combine base options, task keywords, and current SCF options
                    # SCF options should override task/base options if keys conflict
                    current_options = {
                        "basis": task.basis_set,
                        "scf_type": "df",  # Default, might be overridden
                        "freeze_core": "true",
                        **task.additional_keywords,  # User keywords first
                        **scf_options,  # Recovery attempt keywords override
                    }
                    psi4.set_options(current_options)

                    # Run the SAPT calculation
                    psi4.energy(task.method, molecule=psi4_mol)

                    # If psi4.energy() completes without error, SCF converged
                    scf_success = True
                    logger.info(f"SCF converged successfully on attempt {attempt + 1}.")
                    break  # Exit the loop on success

                except psi4.SCFConvergenceError as e:
                    logger.warning(f"SCF convergence failed on attempt {attempt + 1}: {e}")
                    last_scf_error = e
                    # Clean Psi4 environment before next attempt?
                    # psi4.core.clean_options() # Might be needed?
                    # psi4.core.clean_variables() # Might be needed?
                    continue  # Try next set of options
                # Catch other potential Psi4 errors during energy call?
                except Exception as e:
                    logger.error(f"Non-SCF Psi4 error during energy calculation on attempt {attempt+1}: {e}")
                    raise  # Re-raise other Psi4 errors immediately

            # --- End SCF Loop --- #

            # Check if SCF succeeded after all attempts
            if not scf_success:
                error_msg = f"SCF failed to converge after {len(self.SCF_RECOVERY_LADDER)} attempts."
                if last_scf_error: 
                    # Ensure we append the string representation of the last error
                    error_msg += f" Last error: {str(last_scf_error)}"
                # Raise a standard error; the outer handler will catch it.
                raise RuntimeError(error_msg) 
 
            # --- Extract results (only if SCF succeeded) --- #
            result.energies = {
                "total": psi4.variable("SAPT TOTAL ENERGY"),
                "electrostatics": psi4.variable("SAPT ELST ENERGY"),
                "exchange": psi4.variable("SAPT EXCH ENERGY"),
                "induction": psi4.variable("SAPT IND ENERGY"),
                "dispersion": psi4.variable("SAPT DISP ENERGY"),
            }

            # Get the output
            try:
                with open("psi4_output.dat") as f:
                    result.raw_output = f.read()
            except FileNotFoundError:
                pass

            # Update status
            task.status = TaskStatus.COMPLETED
            result.success = True

        except Exception as e:
            # Catch errors from setup phase or re-raised errors from SCF loop
            # Handle any errors
            task.status = TaskStatus.FAILED
            result.success = False
            result.error_message = str(e)

        return result


class CamCaspBackend(SaptBackend):
    """Backend for SAPT calculations using CamCASP.

    This is a placeholder for future implementation.
    """

    def calculate(self, task: SaptTask) -> SaptResult:
        """Placeholder for CamCASP calculation.

        Args:
            task: The SAPT calculation task to perform

        Returns:
            A SaptResult containing the calculation results
        """
        raise NotImplementedError("CamCASP backend is not implemented in MVP")


class Sapt2020Backend(SaptBackend):
    """Backend for SAPT calculations using SAPT2020.

    This is a placeholder for future implementation.
    """

    def calculate(self, task: SaptTask) -> SaptResult:
        """Placeholder for SAPT2020 calculation.

        Args:
            task: The SAPT calculation task to perform

        Returns:
            A SaptResult containing the calculation results
        """
        raise NotImplementedError("SAPT2020 backend is not implemented in MVP")

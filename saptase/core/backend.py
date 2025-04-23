"""Backend implementations for SAPT calculations."""

import logging
import re
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Dict, List, Optional

from .errors import (
    BasisIncompatible,
    MemoryExceeded,
    PsiProgramCrashed,
    SaptError,
    ScfFailed,
)
from .models import SaptResult, SaptTask, TaskStatus

try:
    import psi4
except ImportError:
    psi4 = None  # Allow running the module without Psi4 installed


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
def get_backend(backend_name: str, options: Optional[Dict[str, Any]] = None) -> SaptBackend:
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
        except ImportError as err:
            # This shouldn't happen if orchestrator exists, but good practice.
            raise ValueError("Mock backend requested but MockBackend class not found.") from err
    # Add elif clauses for CamCASP, SAPT2020 etc. when implemented
    # elif backend_name_lower == "camcasp":
    #     return CamCASPBackend(**options)
    else:
        raise ValueError(f"Unsupported backend: {backend_name}")


# --- Setup Logger --- #
logger = logging.getLogger(__name__)

# --- Backend Implementations ---


class Psi4Backend(SaptBackend):
    """Backend for SAPT calculations using the Psi4 quantum chemistry package.

    This backend handles the execution of SAPT calculations via Psi4,
    including setting up the molecular geometry, applying calculation options,
    running the energy calculation, and extracting results.
    It also implements an automatic SCF convergence recovery mechanism.
    """

    # --- Constants for Psi4Backend --- #
    SCF_RECOVERY_LADDER: ClassVar[List[Dict[str, Any]]] = [
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
        """Perform a SAPT calculation using Psi4 with SCF recovery.

        This method sets up and runs the specified SAPT task using Psi4.
        If the initial SCF calculation fails to converge, it automatically
        retries the calculation using a sequence of more robust SCF options
        defined in `SCF_RECOVERY_LADDER`.

        Args:
            task: The SAPT calculation task to perform

        Returns:
            A SaptResult containing the calculation results, or details
            of the failure if the calculation (including recovery attempts)
            is unsuccessful.
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
                logger.info(
                    f"SCF Attempt {attempt + 1}/{len(self.SCF_RECOVERY_LADDER)} "
                    f"using options: {scf_options}"
                )
                psi4.core.clean_variables()  # Clean variables between attempts
                psi4.core.clean_options()  # Clean options between attempts
                # Re-apply base options + task keywords + attempt options
                psi4_options = {
                    "basis": task.basis_set,
                    "scf_type": "df",
                    "freeze_core": "true",
                    **task.additional_keywords,
                    **scf_options,
                }
                psi4.set_options(psi4_options)

                try:
                    # Run the SAPT calculation
                    psi4.energy(task.method, molecule=psi4_mol)

                    # If psi4.energy() completes without error, SCF converged
                    scf_success = True
                    logger.info(f"SCF converged successfully on attempt {attempt + 1}.")
                    break  # Exit the loop on success

                except psi4.SCFConvergenceError as e:
                    logger.warning(f"SCF convergence failed on attempt {attempt + 1}: {e}")
                    last_scf_error = e
                    # Loop will continue to next attempt
                    continue
                except (
                    psi4.ValidationError,
                    psi4.BasisSetNotFound,
                ) as e:  # Catch BasisSetNotFound too
                    error_str = str(e).lower()
                    # Check for keywords indicating a basis set issue
                    if re.search(r"basis set|basisset|could not find basis", error_str):
                        logger.error(f"Basis set error encountered: {e}")
                        raise BasisIncompatible(str(e)) from e
                    else:
                        # If validation error is not basis-related, treat as general crash
                        logger.error(f"Psi4 validation error (non-basis): {e}")
                        raise PsiProgramCrashed(f"Psi4 validation error: {e}") from e
                except psi4.PsiException as e:
                    error_str = str(e).lower()
                    # Check for memory allocation errors
                    if re.search(r"memoryerror|malloc|memory allocation|out of memory", error_str):
                        logger.error(f"Psi4 memory error detected: {e}")
                        raise MemoryExceeded(str(e)) from e
                    else:
                        # General Psi4 exception
                        logger.error(f"Unhandled Psi4 exception: {e}")
                        raise PsiProgramCrashed(f"Psi4 execution failed: {e}") from e
                except Exception as e:
                    # Catch any other unexpected errors during psi4.energy
                    error_str = str(e).lower()
                    if re.search(r"memoryerror|malloc|memory allocation|out of memory", error_str):
                        logger.error(f"Potential memory error detected (non-PsiException): {e}")
                        raise MemoryExceeded(str(e)) from e
                    logger.error(f"Unexpected error during Psi4 calculation: {e}", exc_info=True)
                    raise PsiProgramCrashed(f"Unexpected error: {e}") from e

            # --- After SCF Loop --- #
            if not scf_success:
                logger.error("SCF failed to converge after all recovery attempts.")
                # Raise ScfFailed using the error from the last failed attempt
                raise ScfFailed(str(last_scf_error)) from last_scf_error

            # --- Extract Results (if successful) --- #
            result.success = True
            task.status = TaskStatus.COMPLETED
            # Example: Extract SAPT0 components (adjust for other methods)
            # Ensure variables exist before accessing
            sapt_components = [
                "SAPT0 TOTAL ENERGY",
                "SAPT Electrostatics",
                "SAPT Exchange",
                "SAPT Induction",
                "SAPT Dispersion",
            ]
            for comp in sapt_components:
                var_name = (
                    f"{task.method.upper()} {comp}" if "SAPT0" not in comp else comp
                )  # Handle naming diffs
                if psi4.variable(var_name):
                    # Convert Hartree to kcal/mol
                    result.energies[comp] = psi4.variable(var_name) * 627.509
                else:
                    logger.warning(f"Psi4 variable '{var_name}' not found after successful run.")

            result.raw_output = psi4.core.get_output_file_path()

            # Add basis and method used to the result for provenance
            result.basis_set = task.basis_set
            result.method = task.method

            return result

        except SaptError as e:
            # Catch SaptErrors raised within the loop (BasisIncompatible, MemoryExceeded, etc.)
            # And ScfFailed raised after the loop
            task.status = TaskStatus.FAILED
            result.success = False
            result.error_message = str(e)
            result.error_code = type(e).__name__
            # Log the basis/method even on failure
            result.basis_set = task.basis_set
            result.method = task.method
            logger.error(f"Task {task.id} failed with {type(e).__name__}: {e}")
            # Re-raise the caught SaptError so the orchestrator can handle it
            raise
        except Exception as e:
            # Catch any other unexpected errors during setup/teardown
            task.status = TaskStatus.FAILED
            result.success = False
            result.error_message = f"Unexpected backend error: {e}"
            result.error_code = type(e).__name__  # Or a generic code like 'BackendError'
            # Log the basis/method even on failure
            result.basis_set = task.basis_set
            result.method = task.method
            logger.critical(
                f"Task {task.id} failed with unexpected backend error: {e}", exc_info=True
            )
            # Wrap unexpected errors in PsiProgramCrashed or a new generic BackendError?
            # Let's use PsiProgramCrashed for now, assuming it originates from
            # Psi4 setup/interaction
            error_msg = f"Unexpected backend error: {e}"
            raise PsiProgramCrashed(error_msg) from e
        finally:
            # Ensure Psi4 output file is closed/cleaned if necessary
            # psi4.core.clean() # Maybe too aggressive? Cleans everything.
            # Just ensure the output file handler is released if open
            pass


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

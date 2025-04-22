# saptase/workflows/adaptive.py
"""
Implements the adaptive basis set escalation workflow.
"""

import copy
import math
import logging
from typing import Any, Dict, List, Optional, Tuple, Union, TYPE_CHECKING
from copy import deepcopy

from saptase.core.backend import SaptBackend, Psi4Backend # Import Psi4Backend
from saptase.core.basis import BASIS_LADDER, get_basis_rung, get_next_basis
from saptase.core.models import SaptResult, SaptTask, TaskStatus
from saptase.core.orchestrator import SaptWorkflow
from saptase.core.utils.misc import format_energy_delta

if TYPE_CHECKING:
    # Import the mock backend only for type checking to avoid circular dependencies
    # and keep test-related code out of the main logic's runtime imports.
    from tests.test_adaptive import MockAdaptiveBackend

logger = logging.getLogger(__name__) 

class AdaptiveWorkflow(SaptWorkflow):
    """
    Workflow that adaptively selects the basis set by escalating through a ladder
    until energy component differences fall below specified tolerances.
    """

    def __init__(
        self,
        tasks: List[SaptTask],
        backend_name: str = "psi4",
        backend_options: Optional[Dict[str, Any]] = None,
        adaptive_options: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the adaptive workflow.

        Args:
            tasks: List of SaptTask objects (usually just one for adaptive).
                   The basis set in the initial task defines the starting point,
                   or defaults to the first rung if not specified.
            backend_name: Name of the computational backend (e.g., 'psi4').
            backend_options: Dictionary of options for the backend.
            adaptive_options: Dictionary of options controlling the adaptive behavior.
                              Expected keys: 'target_accuracy' (dict), 'max_rung' (int).
        """
        backend_options = backend_options or {}

        # 1. Instantiate the backend based on name
        if backend_name.lower() == "psi4":
            # Extract relevant options for Psi4Backend, e.g., memory
            psi4_memory = backend_options.get("memory", "2GB") # Default memory
            backend_instance = Psi4Backend(memory=psi4_memory)
        elif backend_name.lower() == "mock": # Allow mock for testing
            # Assumes a MockBackend class exists, maybe in tests or core.backend?
            # For now, let's defer this - how did the tests mock it before?
            # The tests create their own MockAdaptiveBackend. Orchestrator has MockBackend.
            # Let's use the Orchestrator's MockBackend if available, else error.
            try:
                from saptase.core.orchestrator import MockBackend # Local import
                backend_instance = MockBackend()
            except ImportError:
                 raise ValueError(f"Backend 'mock' requires MockBackend to be defined.")

        else:
            # TODO: Add CamCASP, SAPT2020 when implemented
            raise ValueError(f"Unsupported backend: {backend_name}")

        # 2. Initialize the base class correctly using keyword arguments
        super().__init__(tasks=tasks, backend=backend_instance)

        # --- Now initialize AdaptiveWorkflow specific attributes ---
        self.adaptive_options = adaptive_options or {}
        self.target_accuracy = self.adaptive_options.get("target_accuracy", {})
        # Default max_rung is the top of the ladder
        self.max_rung = self.adaptive_options.get(
            "max_rung", len(BASIS_LADDER) - 1
        )
        self.results_by_rung: Dict[int, SaptResult] = {} # Store results per rung

        if not self.target_accuracy:
            logger.warning("No target accuracy specified for adaptive workflow.") 

        if len(self.tasks) > 1:
            # For now, just use the first task for adaptive logic
            logger.warning(
                "Adaptive workflow currently handles only the first task provided."
            )
        self.primary_task_id = self.tasks[0].id if self.tasks else None # This should work now
        self.primary_task_ref = self.tasks[0] if self.tasks else None # Keep reference


    def run_adaptive(self, max_workers: Optional[int] = None) -> Dict[str, SaptResult]:
        """
        Executes the adaptive workflow for the primary task.

        Iteratively runs SAPT calculations with increasing basis sets from the
        BASIS_LADDER until the energy components converge according to
        `self.target_accuracy` or `self.max_rung` is reached.

        Args:
            max_workers: Maximum number of parallel workers (passed to backend if supported).
                         Currently unused in the adaptive logic itself but stored.

        Returns:
            A dictionary containing the final converged SaptResult mapped by task ID,
            or all results obtained if convergence is not reached or failure occurs.
        """
        if not self.primary_task_ref: # Check the reference task object
            logger.error("Adaptive workflow started with no tasks.")
            return {}

        # Clear previous results specific to this run
        self.results.clear() # Clear the main results dict from base class
        self.results_by_rung.clear()

        # Use the reference task to get the starting basis
        current_basis = self.primary_task_ref.basis_set
        current_rung = get_basis_rung(current_basis)

        if current_rung is None:
            logger.warning(
                f"Initial basis '{current_basis}' not found in BASIS_LADDER. Starting from rung 0."
            )
            current_rung = 0
            current_basis = BASIS_LADDER[current_rung]

        logger.info(f"Starting adaptive workflow at rung {current_rung} ({current_basis})...")
        logger.info(f"Target Accuracy: {self.target_accuracy}")
        logger.info(f"Max Rung: {self.max_rung} ({BASIS_LADDER[self.max_rung]}) ")

        prev_result: Optional[SaptResult] = None
        final_converged_result: Optional[SaptResult] = None

        while current_rung <= self.max_rung:
            logger.info(f"--- Running Rung {current_rung} ({current_basis}) ---")
            task_for_rung = deepcopy(self.primary_task_ref) # Use deepcopy
            task_for_rung.basis_set = current_basis
            # Use a unique ID for the specific rung calculation for internal tracking
            rung_task_id = f"{self.primary_task_id}_rung{current_rung}"
            task_for_rung.id = rung_task_id
            task_for_rung.status = TaskStatus.PENDING # Ensure status is reset

            # Execute the calculation for the current rung
            current_result = None
            try:
                # Check if using the mock backend for testing
                # This avoids pickling issues with mock lambdas when using run_local_serial
                if self.backend.__class__.__name__ == 'MockAdaptiveBackend':
                    current_result = self.backend.calculate(task_for_rung)
                    # Manually update the main results dict for consistency if needed later
                    self.results[rung_task_id] = current_result
                else:
                    # Use the base class method for real backends
                    self.run_local_serial([task_for_rung])
                    current_result = self.results.get(rung_task_id)

            except Exception as e:
                logger.error(f"Exception during rung {current_rung} execution: {e}", exc_info=True)
                # Create a failure result
                current_result = SaptResult(
                    task_id=rung_task_id,
                    success=False,
                    error_message=f"Execution failed: {e}"
                )
                self.results[rung_task_id] = current_result # Ensure failure is recorded

            if not current_result:
                 # This case should ideally not happen if execution completes
                 logger.error(f"Result for task {rung_task_id} not found after execution.")
                 current_result = SaptResult(task_id=rung_task_id, success=False, error_message="Result missing after execution")
                 self.results[rung_task_id] = current_result

            # Store result by rung index as well for convergence check
            self.results_by_rung[current_rung] = current_result

            if not current_result.success:
                logger.error(
                    f"Calculation failed at rung {current_rung} ({current_basis}): "
                    f"{current_result.error_message}"
                )
                # Return all results obtained so far (keyed by rung_task_id)
                return self.results

            logger.info(f"Rung {current_rung} completed successfully.")
            logger.debug(f"Energies ({current_basis}): {current_result.energies}")

            # Check for convergence (only if not the first rung)
            if prev_result is not None:
                converged, reasons = self._check_convergence(prev_result, current_result)
                logger.info("Convergence Check:")
                for key, reason in reasons.items():
                    logger.info(f"  - {key}: {reason}")

                if converged:
                    logger.info(
                        f"Convergence reached at rung {current_rung} ({current_basis}). "
                        f"Final Result Task ID: {current_result.task_id}"
                    )
                    final_converged_result = current_result
                    break # Exit the loop upon convergence
                else:
                     logger.info(f"Not converged after rung {current_rung}.")

            # Prepare for the next rung
            if current_rung == self.max_rung:
                logger.warning(
                    f"Reached maximum rung ({self.max_rung}) without convergence."
                )
                # Loop will terminate naturally
                break

            # Get next basis
            next_basis = get_next_basis(current_basis)
            if next_basis is None: # Should not happen if max_rung is respected
                 logger.error(f"Could not get next basis after {current_basis}. Stopping.")
                 break # Exit loop

            # Update for next iteration
            prev_result = current_result
            current_basis = next_basis
            current_rung += 1
        # --- End of while loop ---

        # Prepare final return dictionary
        if final_converged_result:
            # Return the final converged result keyed by the original primary task ID
            # The final_converged_result object already has the correct data, just use it.
            return {self.primary_task_id: final_converged_result}
        else:
            # If loop finished due to max_rung or other reasons without convergence,
            # return all results obtained (keyed by rung_task_id as they were stored)
            logger.info("Adaptive workflow finished without full convergence.")
            return self.results

    def _check_convergence(
        self,
        prev_result: SaptResult,
        curr_result: SaptResult,
    ) -> Tuple[bool, Dict[str, str]]:
        """Check convergence between two consecutive SAPT results based on options.

        Args:
            prev_result: The SaptResult from the previous rung.
            curr_result: The SaptResult from the current rung.

        Returns:
            A tuple containing:
                - bool: True if all specified components converged, False otherwise.
                - dict: A dictionary with convergence reasons for each component.
        """
        target_accuracy = self.adaptive_options.get("target_accuracy", {})
        if not target_accuracy:
            return False, {} # Cannot converge without criteria

        # Internal mapping from target_accuracy keys to SaptResult.energies keys
        # Assumes SaptResult.energies uses simplified keys internally
        key_mapping = {
            "sapt_total": "total",
            "elst": "elst",
            "exch": "exch",
            "ind": "ind",
            "disp": "disp",
            # Add other potential mappings if needed
        }

        reasons = {}
        # Assume convergence until proven otherwise
        all_converged = True

        if not prev_result.energies or not curr_result.energies:
            reasons["error"] = "Missing energy components in one or both results."
            return False, reasons

        prev_energies = prev_result.energies
        curr_energies = curr_result.energies

        for target_key, tolerance in target_accuracy.items():
            internal_key = key_mapping.get(target_key)

            if not internal_key:
                reason = f"key '{target_key}' not found in internal mapping, skipping."
                reasons[target_key] = reason
                logger.warning(f"Convergence check skipped for {target_key}: {reason}")
                # Do not fail convergence for an unmappable key
                continue

            prev_val = prev_energies.get(internal_key)
            curr_val = curr_energies.get(internal_key)

            if prev_val is None or curr_val is None:
                reason = f"Energy value for '{internal_key}' missing in one or both rungs."
                reasons[target_key] = reason
                all_converged = False # Cannot converge if component is missing
                logger.warning(f"Convergence check failed for {target_key}: {reason}")
                continue

            delta = abs(curr_val - prev_val)
            converged = delta <= tolerance

            if converged:
                reasons[target_key] = format_energy_delta(
                    delta, tolerance, converged, target_key
                )
            else:
                reasons[target_key] = format_energy_delta(
                    delta, tolerance, converged, target_key
                )
                all_converged = False # Set to False if any component fails

        return all_converged, reasons

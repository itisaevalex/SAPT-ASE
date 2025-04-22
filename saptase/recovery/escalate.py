# saptase/recovery/escalate.py
"""Manages error recovery strategies and escalation attempts."""

import logging
import copy
from typing import Dict, Any, List, Tuple, Optional, Type, Callable

from saptase.core.models import SaptTask
from saptase.core.errors import SaptError, ScfFailed, BasisIncompatible, MemoryExceeded

from .strategies import (
    recover_basis_incompatible,
    recover_scf_failed_simple,
    recover_memory_exceeded,
    # Import others as needed
)

logger = logging.getLogger(__name__)

# Define the Recovery Ladder
# List of tuples: (ErrorType, StrategyFunction)
# Order matters - defines the escalation sequence
LADDER: List[Tuple[Type[SaptError], Callable[[SaptTask, SaptError], SaptTask]]] = [
    (BasisIncompatible, recover_basis_incompatible), # First, try changing basis if incompatible
    (ScfFailed, recover_scf_failed_simple), # If SCF fails, try simple relaxation
    (MemoryExceeded, recover_memory_exceeded), # If memory fails, try reducing it
    # Add more strategies here, e.g.:
    # (ScfFailed, recover_scf_advanced), # Try more advanced SCF options
    # (PsiProgramCrashed, reduce_level_of_theory), # If crashing, try lower theory
]

# Create a map for faster lookup
# LADDER_MAP: Dict[Type[SaptError], Callable[[SaptTask, SaptError], SaptTask]] = dict(LADDER)

# Maximum recovery attempts per task
MAX_ATTEMPTS = 3 # Original run + MAX_ATTEMPTS retries


class EscalationContext:
    """Manages the recovery process for a single SaptTask."""

    def __init__(self, task: SaptTask, max_attempts: int = MAX_ATTEMPTS):
        self.original_task = task
        self.max_attempts = max_attempts
        self.attempt_count = 0 # Starts at 0 for the initial run
        self.last_error: Optional[SaptError] = None
        self.history: list[dict] = [] # Initialize history
        logger.debug(f"Initialized EscalationContext for task {task.id} with max {max_attempts} retries.")

    def can_retry(self, error: SaptError) -> bool:
        """Check if another recovery attempt can be made."""
        self.last_error = error # Store the error that triggered this check
        # Attempt count starts at 0, so we check against max_attempts
        can = self.attempt_count < self.max_attempts
        if not can:
            logger.warning(f"Task {self.original_task.id}: Max attempts ({self.max_attempts}) reached. Cannot retry further.")
        return can

    def _get_strategy_for_error(self, error: SaptError) -> Optional[Callable]:
        """Find the appropriate strategy from the LADDER based on the current attempt count."""
        # Attempt count starts at 1 for the first retry, LADDER is 0-indexed.
        strategy_index = self.attempt_count - 1

        if not (0 <= strategy_index < len(LADDER)):
            logger.warning(f"Task {self.original_task.id}: Invalid strategy index ({strategy_index}) for attempt {self.attempt_count}. Max attempts likely reached or index error.")
            return None

        # Get the strategy designated for this attempt number
        # We don't strictly need to check the error type here, as the ladder dictates the sequence.
        # The check in can_retry confirms if *any* strategy applies for the given error initially.
        _expected_error_type, strategy_func = LADDER[strategy_index]

        logger.debug(f"Task {self.original_task.id}: Selected strategy {strategy_func.__name__} for attempt {self.attempt_count} based on error {type(error).__name__}.")
        return strategy_func

    def apply(self) -> SaptTask:
        """Apply the next recovery strategy from the LADDER.

        Returns:
            A *copy* of the original task with modifications applied for the retry.
        Raises:
            RuntimeError: If called when no more retries are possible or ladder exhausted.
            NotImplementedError: If a strategy requires logic not yet implemented.
        """
        if not self.last_error or not self.can_retry(self.last_error):
             # Re-check can_retry just in case state changed, use stored error
            raise RuntimeError("Cannot apply recovery: maximum attempts reached or no error recorded.")

        # Increment attempt count *before* applying strategy for the *next* attempt
        self.attempt_count += 1
        strategy_func = self._get_strategy_for_error(self.last_error)

        if strategy_func is None:
            logger.error(f"Task {self.original_task.id}: No strategy available for attempt {self.attempt_count}.")
            # This technically shouldn't be reached if max_attempts <= len(LADDER)
            # but acts as a safeguard.
            self.attempt_count = self.max_attempts # Ensure can_retry returns False next time
            raise RuntimeError("Exhausted recovery ladder strategies.")

        logger.info(f"Task {self.original_task.id}: Applying recovery strategy (Attempt {self.attempt_count}/{self.max_attempts}): '{strategy_func.__name__}'")

        # Create a deep copy to avoid modifying the original task or previous attempts
        retry_task = copy.deepcopy(self.original_task)
        # Assign a new unique ID or modify existing one to indicate retry attempt
        retry_task.id = f"{self.original_task.id}_retry_{self.attempt_count}" # Added underscore
        retry_task.status = "RETRYING"
        retry_task.error_message = f"Retrying after error: {type(self.last_error).__name__}"
        retry_task.attempt_number = self.attempt_count

        # Apply strategy modifications
        retry_task = strategy_func(retry_task, self.last_error)

        # Record the attempt
        self.history.append({ # Append to history
            "attempt": self.attempt_count,
            "error_type": type(self.last_error).__name__,
            "strategy_name": strategy_func.__name__, # Store name instead of function
            "outcome_task_id": retry_task.id,
            # Could add specific changes made here if needed
        })

        return retry_task

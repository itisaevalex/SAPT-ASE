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
RecoveryStrategy = Tuple[Type[SaptError], Callable[[SaptTask, SaptError], SaptTask]]
LADDER: List[RecoveryStrategy] = [
    (BasisIncompatible, recover_basis_incompatible),
    (ScfFailed, recover_scf_failed_simple), # First SCF strategy
    (MemoryExceeded, recover_memory_exceeded),
    # Example: Add a second SCF strategy
    # (ScfFailed, recover_scf_advanced),
]

# Create a map for faster lookup (Optional, not used with current logic)
# LADDER_MAP: Dict[Type[SaptError], Callable[[SaptTask, SaptError], SaptTask]] = dict(LADDER)

# Default max_attempts for the context should ideally match workflow default retries
# Represents the number of *retries* allowed after the initial failure.
MAX_ATTEMPTS = 5 # Let's align this with the likely SaptWorkflow default


class EscalationContext:
    """Manages the recovery process for a single SaptTask."""

    def __init__(self, task: SaptTask, max_attempts: int = MAX_ATTEMPTS):
        self.original_task = task
        # max_attempts here refers to the total number of *retries* allowed.
        # So total runs = 1 (initial) + max_attempts (retries)
        self.max_attempts = max_attempts
        self.attempt_count = 0 # Counts retries (0 means initial run hasn't failed yet for context)
        self.last_error: Optional[SaptError] = None
        self.history: list[dict] = []
        self.last_strategy_index = -1 # Index in LADDER of the last strategy applied
        logger.debug(f"Initialized EscalationContext for task {task.id} with max {max_attempts} retries.")

    def record_failure(self, error: SaptError):
        """Records the error that occurred, preparing for a potential retry."""
        self.last_error = error
        # attempt_count is incremented when apply() is called for a retry.

    def can_retry(self) -> bool:
        """Check if another recovery attempt can be made based on counts and available strategies."""
        if self.attempt_count >= self.max_attempts:
            logger.warning(f"Task {self.original_task.id}: Max attempts ({self.max_attempts}) reached. Cannot retry further.")
            return False
        # Check if there's actually a strategy available for the last error
        # This prevents retrying if the error isn't handled by any strategy
        strategy_info = self._find_next_strategy()
        if strategy_info is None:
             logger.warning(f"Task {self.original_task.id}: No further applicable recovery strategy found for error {type(self.last_error).__name__} after attempt {self.attempt_count}.")
             return False
        return True

    def _find_next_strategy(self) -> Optional[Tuple[int, Callable]]:
        """Find the index and function of the next applicable strategy in the LADDER."""
        if not self.last_error:
            return None # No error to find a strategy for

        # Start searching *after* the last applied strategy
        start_index = self.last_strategy_index + 1
        for i in range(start_index, len(LADDER)):
            error_type, strategy_func = LADDER[i]
            if isinstance(self.last_error, error_type):
                # Found the next applicable strategy
                logger.debug(f"Task {self.original_task.id}: Found next strategy {strategy_func.__name__} at index {i} for error {type(self.last_error).__name__}.")
                return i, strategy_func

        # No more strategies found in the ladder for this error type
        return None

    def apply(self) -> SaptTask:
        """Apply the next suitable recovery strategy."""
        if not self.last_error:
            raise RuntimeError("Cannot apply recovery: no error has been recorded.")
        if self.attempt_count >= self.max_attempts:
             raise RuntimeError(f"Cannot apply recovery: maximum attempts ({self.max_attempts}) reached.")

        strategy_info = self._find_next_strategy()
        if strategy_info is None:
            logger.error(f"Task {self.original_task.id}: No suitable *next* recovery strategy found for error {type(self.last_error).__name__}.")
            raise RuntimeError(f"No suitable *next* recovery strategy found for {type(self.last_error).__name__}.")

        # Found a strategy, increment attempt count and store strategy index
        self.attempt_count += 1
        strategy_index, strategy_func = strategy_info
        self.last_strategy_index = strategy_index # Remember which strategy we are applying

        logger.info(f"Task {self.original_task.id}: Applying recovery strategy (Retry {self.attempt_count}/{self.max_attempts}): '{strategy_func.__name__}'")

        # --- Create retry task ---
        retry_task = copy.deepcopy(self.original_task)
        retry_task.id = f"{self.original_task.id}_retry_{self.attempt_count}"
        # Note: SaptWorkflow now sets status, error_message, attempt_number before calling backend
        # So we don't strictly need to set them here, but applying strategy might use them.
        retry_task.status = "RETRYING"
        retry_task.error_message = f"Retrying after error: {type(self.last_error).__name__}"
        retry_task.attempt_number = self.attempt_count # Retry number (1-based)

        # --- Apply strategy modifications ---
        try:
             modified_task = strategy_func(retry_task, self.last_error)
        except Exception as e:
             logger.exception(f"Task {self.original_task.id}: Error applying strategy {strategy_func.__name__} on retry {self.attempt_count}.")
             # Re-raise or handle? If strategy fails, maybe task should fail permanently?
             # For now, let the exception propagate, which should fail the task.
             raise RuntimeError(f"Strategy application failed: {e}") from e


        # --- Record history ---
        self.history.append({
            "retry_attempt": self.attempt_count,
            "error_type": type(self.last_error).__name__,
            "strategy_name": strategy_func.__name__,
            "strategy_index": self.last_strategy_index,
            "outcome_task_id": modified_task.id,
        })

        return modified_task # Return the task modified by the strategy

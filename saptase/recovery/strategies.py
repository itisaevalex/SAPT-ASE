# saptase/recovery/strategies.py
"""Contains individual recovery strategy functions."""

import copy
import logging

from saptase.core.models import SaptTask
from saptase.core.basis import get_previous_basis # Use this for basis incompatibility

logger = logging.getLogger(__name__)

# --- Strategy Implementations --- #

def recover_basis_incompatible(task: SaptTask, error: Exception) -> SaptTask:
    """Strategy: Switch to the previous (smaller) basis set in the ladder."""
    new_task = copy.deepcopy(task)
    try:
        original_basis = new_task.basis_set
        new_basis = get_previous_basis(original_basis) # Try smaller basis
        if new_basis is None:
            logger.warning(f"Recovery failed for Task {task.id} - BasisIncompatible: Cannot find a smaller basis than '{original_basis}'.")
            return task # Signal failure

        new_task.basis_set = new_basis
        logger.info(f"Recovery: Task {task.id} - BasisIncompatible. Switched basis from '{original_basis}' to '{new_basis}'.")
        new_task.additional_keywords["recovery_strategy"] = recover_basis_incompatible.__name__
    except ValueError as e:
        logger.warning(f"Recovery failed for Task {task.id} - BasisIncompatible: {e}")
        # Should not happen if get_previous_basis handles lookup failure
        # For now, return original task to signal failure of strategy
        return task
    return new_task

def recover_scf_failed_simple(task: SaptTask, error: Exception) -> SaptTask:
    """Strategy: Relax SCF convergence criteria and increase iterations."""
    new_task = copy.deepcopy(task)
    # Get current or default values
    current_d_conv = new_task.additional_keywords.get("d_convergence", 1e-7)
    current_e_conv = new_task.additional_keywords.get("e_convergence", 1e-7)
    current_maxiter = new_task.additional_keywords.get("maxiter", 50)

    # Apply simple recovery keywords (make less stringent)
    new_task.additional_keywords["d_convergence"] = min(1e-5, current_d_conv * 10) # Relax by factor of 10, capped
    new_task.additional_keywords["e_convergence"] = min(1e-5, current_e_conv * 10)
    new_task.additional_keywords["maxiter"] = current_maxiter + 50 # Increase iterations
    # Potentially add level shifting or SOSCF if simple relaxation fails
    # new_task.additional_keywords["level_shift"] = 0.3
    # new_task.additional_keywords["soscf"] = "true"

    logger.info(f"Recovery: Task {task.id} - ScfFailed. Relaxed convergence and increased maxiter.")
    new_task.additional_keywords["recovery_strategy"] = recover_scf_failed_simple.__name__
    return new_task

def recover_memory_exceeded(task: SaptTask, error: Exception) -> SaptTask:
    """Strategy: Reduce memory allocation request."""
    new_task = copy.deepcopy(task)
    current_mem_str = new_task.additional_keywords.get("memory")
    if current_mem_str:
        try:
            # Basic parsing (assumes "X GB" or "X MB") - needs improvement
            parts = current_mem_str.split()
            value = float(parts[0])
            unit = parts[1].upper()
            # Reduce by 20% (example)
            reduced_value = value * 0.8
            new_mem_str = f"{reduced_value:.1f} {unit}"
            new_task.additional_keywords["memory"] = new_mem_str
            logger.info(f"Recovery: Task {task.id} - MemoryExceeded. Reduced memory from '{current_mem_str}' to '{new_mem_str}'.")
        except (IndexError, ValueError):
            logger.warning(f"Recovery failed for Task {task.id} - MemoryExceeded: Could not parse memory string '{current_mem_str}'.")
            # Return original task if parsing fails
            return task
    else:
        # If no memory was set, maybe set a default low value?
        # For now, signal failure by returning original task
        logger.warning(f"Recovery failed for Task {task.id} - MemoryExceeded: No initial memory additional_keyword found.")
        return task

    new_task.additional_keywords["recovery_strategy"] = recover_memory_exceeded.__name__
    return new_task

# --- Add other strategy implementations as needed --- #

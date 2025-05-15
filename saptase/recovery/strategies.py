# saptase/recovery/strategies.py
"""Recovery strategies for SAPT calculations.

This module defines the strategies that can be applied to recover from errors.
Each strategy is a function that modifies a SaptTask to enable recovery.
"""

import copy
import logging

from saptase.core.basis import (
    BASIS_LADDER,
    get_basis_rung,
    get_next_basis,
)
from saptase.core.models import SaptTask

logger = logging.getLogger(__name__)


def recover_basis_incompatible(task: SaptTask) -> SaptTask:
    """Strategy: Escalate to the next basis set in the ladder.

    If the current basis is not in the ladder, it defaults to the first
    basis in the ladder (if BASIS_LADDER is not empty).
    If already at the highest rung, signals failure.

    Args:
        task: The failed task

    Returns:
        A new SaptTask with the escalated or default basis set, or the
        original task if escalation is not possible.
    """
    new_task = copy.deepcopy(task)
    original_basis = new_task.basis_set

    # Attempt to get the next basis. If the original_basis is not in the ladder,
    # this will return the first basis from the ladder due to fallback_first=True.
    # If original_basis is the last in the ladder, this will return None.
    new_basis = get_next_basis(original_basis, fallback_first=True)

    if new_basis is None:
        # This means either:
        # 1. original_basis was the last in the ladder.
        # 2. original_basis was not in the ladder AND fallback_first=True returned None
        #    (which happens if BASIS_LADDER is empty, though first_rung() would error then,
        #    or if get_next_basis logic changes - current patch returns first_rung() if ladder not empty).
        #    The new get_next_basis returns first_rung() if not found and fallback_first=True,
        #    so this path is mainly for "already at top of ladder".

        current_rung = get_basis_rung(original_basis)  # Check if it was in ladder
        if current_rung is not None and current_rung == len(BASIS_LADDER) - 1:
            logger.warning(
                f"Recovery failed for Task {task.id} - BasisIncompatible: "
                f"Cannot find a larger basis than '{original_basis}' (already at top of ladder)."
            )
        elif not BASIS_LADDER:  # Explicitly check for empty ladder
            logger.warning(
                f"Recovery failed for Task {task.id} - BasisIncompatible: "
                f"Original basis '{original_basis}'. BASIS_LADDER is empty."
            )
        else:  # Should not happen with current get_next_basis logic if fallback_first=True
            logger.warning(
                f"Recovery failed for Task {task.id} - BasisIncompatible: "
                f"No suitable next basis found for '{original_basis}' even with fallback. "
                f"This might indicate an issue or an empty BASIS_LADDER."
            )
        return task  # Signal failure

    # Log the recovery action
    if (
        original_basis == new_basis
    ):  # This can happen if fallback_first was used and original_basis was not in ladder
        logger.info(
            f"Recovery: Task {task.id} - BasisIncompatible. "
            f"Original basis '{original_basis}' not in ladder or invalid. "
            f"Attempting first ladder basis '{new_basis}'."
        )
    else:
        logger.info(
            f"Recovery: Task {task.id} - BasisIncompatible. "
            f"Escalating basis from '{original_basis}' to '{new_basis}'."
        )

    new_task.basis_set = new_basis
    new_task.additional_keywords["recovery_strategy"] = "recover_basis_incompatible_escalate"
    new_task.additional_keywords.pop("previous_basis_set", None)

    return new_task


def recover_scf_failed_simple(task: SaptTask) -> SaptTask:
    """Strategy: Add level shift, relax convergence, and increase iterations.

    Args:
        task: The failed task

    Returns:
        A new SaptTask with modified SCF parameters
    """
    new_task = copy.deepcopy(task)

    # Get current or default values
    current_d_conv = new_task.additional_keywords.get("d_convergence", 1e-7)
    current_e_conv = new_task.additional_keywords.get("e_convergence", 1e-7)
    current_maxiter = new_task.additional_keywords.get("maxiter", 50)

    # Apply simple recovery keywords
    new_task.additional_keywords["level_shift"] = 0.5
    new_task.additional_keywords["d_convergence"] = min(
        1e-5, current_d_conv * 10
    )  # Relax by factor of 10, capped
    new_task.additional_keywords["e_convergence"] = min(1e-5, current_e_conv * 10)
    new_task.additional_keywords["maxiter"] = current_maxiter + 50  # Increase iterations
    new_task.additional_keywords["recovery_strategy"] = "recover_scf_failed_simple"

    logger.info(
        f"Recovery: Task {task.id} - ScfFailed. "
        f"Added level_shift, relaxed convergence, increased maxiter."
    )
    return new_task


def recover_scf_failed_advanced(task: SaptTask) -> SaptTask:
    """Strategy: Add SOSCF and direct inversion options for difficult convergence cases.

    Args:
        task: The failed task

    Returns:
        A new SaptTask with advanced SCF parameters
    """
    new_task = copy.deepcopy(task)

    # Apply advanced recovery keywords
    new_task.additional_keywords["level_shift"] = 0.5
    new_task.additional_keywords["soscf"] = "true"
    new_task.additional_keywords["direct_p_space"] = "true"
    new_task.additional_keywords["maxiter"] = 200
    new_task.additional_keywords["recovery_strategy"] = "recover_scf_failed_advanced"

    logger.info(
        f"Recovery: Task {task.id} - ScfFailed (advanced). "
        f"Added SOSCF and direct inversion techniques."
    )
    return new_task


def recover_memory_exceeded(task: SaptTask) -> SaptTask:
    """Strategy: Reduce memory allocation request.

    Args:
        task: The failed task

    Returns:
        A new SaptTask with reduced memory allocation
    """
    new_task = copy.deepcopy(task)

    # Check for memory specification
    current_mem_str = new_task.additional_keywords.get("memory")
    if not current_mem_str:
        logger.warning(
            f"Recovery failed for Task {task.id} - MemoryExceeded: "
            f"No memory specification found."
        )
        return task  # Signal failure

    # Parse current memory
    try:
        if "GB" in current_mem_str:
            current_mem = float(current_mem_str.replace("GB", "").strip())
            units = "GB"
        elif "MB" in current_mem_str:
            current_mem = float(current_mem_str.replace("MB", "").strip())
            units = "MB"
        else:
            # Default to GB if not specified
            current_mem = float(current_mem_str.strip())
            units = "GB"

        # Reduce by 20%
        new_mem = current_mem * 0.8

        # Set minimum thresholds
        if units == "GB" and new_mem < 1.0:
            new_mem = 1.0  # Minimum 1GB
        elif units == "MB" and new_mem < 500:
            new_mem = 500  # Minimum 500MB

        new_mem_str = f"{new_mem} {units}"
        new_task.additional_keywords["memory"] = new_mem_str
        new_task.additional_keywords["recovery_strategy"] = "recover_memory_exceeded"

        logger.info(
            f"Recovery: Task {task.id} - MemoryExceeded. "
            f"Reduced memory from '{current_mem_str}' to '{new_mem_str}'."
        )
    except (ValueError, TypeError) as e:
        logger.warning(f"Recovery failed for Task {task.id} - MemoryExceeded: {e}")
        return task  # Signal failure

    return new_task

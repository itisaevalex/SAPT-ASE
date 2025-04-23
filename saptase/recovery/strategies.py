# saptase/recovery/strategies.py
"""Recovery strategies for SAPT calculations.

This module defines the strategies that can be applied to recover from errors.
Each strategy is a function that modifies a SaptTask to enable recovery.
"""

import copy
import logging
from typing import Dict, Any, Optional

from saptase.core.models import SaptTask
from saptase.core.basis import get_previous_basis

logger = logging.getLogger(__name__)


def recover_basis_incompatible(task: SaptTask) -> SaptTask:
    """Strategy: Switch to the previous (smaller) basis set in the ladder.
    
    Args:
        task: The failed task

    Returns:
        A new SaptTask with the smaller basis set
    """
    new_task = copy.deepcopy(task)
    try:
        original_basis = new_task.basis_set
        new_basis = get_previous_basis(original_basis)
        
        if new_basis is None:
            logger.warning(f"Recovery failed for Task {task.id} - BasisIncompatible: "
                          f"Cannot find a smaller basis than '{original_basis}'.") 
            return task  # Signal failure by returning original task unchanged
            
        new_task.basis_set = new_basis
        new_task.additional_keywords["recovery_strategy"] = "recover_basis_incompatible"
        logger.info(f"Recovery: Task {task.id} - BasisIncompatible. "
                   f"Switched basis from '{original_basis}' to '{new_basis}'.") 
    except ValueError as e:
        logger.warning(f"Recovery failed for Task {task.id} - BasisIncompatible: {e}")
        return task  # Signal failure
        
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
    new_task.additional_keywords["d_convergence"] = min(1e-5, current_d_conv * 10)  # Relax by factor of 10, capped
    new_task.additional_keywords["e_convergence"] = min(1e-5, current_e_conv * 10)
    new_task.additional_keywords["maxiter"] = current_maxiter + 50  # Increase iterations
    new_task.additional_keywords["recovery_strategy"] = "recover_scf_failed_simple"
    
    logger.info(f"Recovery: Task {task.id} - ScfFailed. "
               f"Added level_shift, relaxed convergence, increased maxiter.")
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
    
    logger.info(f"Recovery: Task {task.id} - ScfFailed (advanced). "
               f"Added SOSCF and direct inversion techniques.")
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
        logger.warning(f"Recovery failed for Task {task.id} - MemoryExceeded: "
                      f"No memory specification found.")
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
        
        logger.info(f"Recovery: Task {task.id} - MemoryExceeded. "
                   f"Reduced memory from '{current_mem_str}' to '{new_mem_str}'.") 
    except (ValueError, TypeError) as e:
        logger.warning(f"Recovery failed for Task {task.id} - MemoryExceeded: {e}")
        return task  # Signal failure
        
    return new_task

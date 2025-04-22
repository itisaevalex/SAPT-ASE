"""Basis set handling for SAPT calculations.

This module contains utilities for managing basis sets in SAPT calculations.
For the MVP, this is a minimal implementation with just the fixed jun-cc-pVDZ basis.
"""

from typing import Optional

# Default basis set for MVP
DEFAULT_BASIS = "jun-cc-pVDZ"

# Mapping of orbital basis sets to corresponding density fitting basis sets
DF_BASIS_MAP = {
    "jun-cc-pVDZ": "jun-cc-pVDZ-jkfit",
    "aug-cc-pVDZ": "aug-cc-pVDZ-jkfit",
    "jun-cc-pVTZ": "jun-cc-pVTZ-jkfit",
    "aug-cc-pVTZ": "aug-cc-pVTZ-jkfit",
    "def2-SVP": "def2-universal-jkfit",
    "def2-TZVP": "def2-universal-jkfit",
    "def2-TZVPP": "def2-universal-jkfit",
    "def2-TZVPPD": "def2-universal-jkfit",
}

# Basis set ladder from lowest to highest accuracy
BASIS_LADDER = ["jun-cc-pVDZ", "aug-cc-pVDZ", "jun-cc-pVTZ", "aug-cc-pVTZ"]


def get_df_basis(orbital_basis: str) -> str:
    """Get the appropriate density fitting basis for an orbital basis.

    Args:
        orbital_basis: The orbital basis set name

    Returns:
        The corresponding density fitting basis set name
    """
    return DF_BASIS_MAP.get(orbital_basis, f"{orbital_basis}-jkfit")


def get_next_basis(current_basis: str) -> Optional[str]:
    """Get the next basis set in the ladder.

    Args:
        current_basis: The current basis set name

    Returns:
        The next basis set in the ladder, or None if at the top
    """
    try:
        idx = BASIS_LADDER.index(current_basis)
        if idx < len(BASIS_LADDER) - 1:
            return BASIS_LADDER[idx + 1]
    except ValueError:
        # If not in ladder, return the first rung
        return BASIS_LADDER[0]

    return None  # Already at the top of the ladder

"""Basis set handling for SAPT calculations.

This module contains utilities for managing basis sets in SAPT calculations.
For the MVP, this is a minimal implementation with just the fixed jun-cc-pVDZ basis.
"""

from typing import Optional, List, Dict

# Default basis set for MVP
DEFAULT_BASIS = "jun-cc-pvdz"

# Explicit mapping for density fitting basis sets (lowercase keys)
DF_BASIS_MAP: Dict[str, str] = {
    # Psi4 recommends specific matching JKFIT basis for RI-MP2/SAPT
    "cc-pvdz": "cc-pvdz-jkfit",
    "aug-cc-pvdz": "aug-cc-pvdz-jkfit",
    "cc-pvtz": "cc-pvtz-jkfit",
    "aug-cc-pvtz": "aug-cc-pvtz-jkfit",
    "cc-pvqz": "cc-pvqz-jkfit",
    "aug-cc-pvqz": "aug-cc-pvqz-jkfit",
    # General def2 mapping
    "def2-svp": "def2-universal-jkfit",
    "def2-svpd": "def2-universal-jkfit",
    "def2-tzvp": "def2-universal-jkfit",
    "def2-tzvpd": "def2-universal-jkfit",
    "def2-tzvpp": "def2-universal-jkfit",
    "def2-tzvppd": "def2-universal-jkfit",
    "def2-qzvp": "def2-universal-jkfit",
    "def2-qzvpd": "def2-universal-jkfit",
    "def2-qzvpp": "def2-universal-jkfit",
    "def2-qzvppd": "def2-universal-jkfit",
}

# Standard basis set ladder, ordered by increasing size/cost (lowercase)
BASIS_LADDER: List[str] = [
    "jun-cc-pvdz",
    "aug-cc-pvdz",
    "jun-cc-pvtz",
    "aug-cc-pvtz",
    # TODO: Consider adding QZ level if needed
]


def get_df_basis(orbital_basis: str) -> str:
    """Get the corresponding density fitting basis set.

    Looks up in the explicit map first (case-insensitively),
    then defaults to appending '-jkfit' to the lowercase orbital basis name.

    Args:
        orbital_basis: The name of the orbital basis set.

    Returns:
        The name of the density fitting basis set.
    """
    lower_basis = orbital_basis.lower()
    # Get from map (which now has lowercase keys), or apply default rule
    return DF_BASIS_MAP.get(lower_basis, f"{lower_basis}-jkfit")


def get_basis_rung(basis_set_name: str) -> Optional[int]:
    """Finds the index (rung) of a given basis set in the BASIS_LADDER.

    Comparison is case-insensitive.

    Args:
        basis_set_name: The name of the basis set.

    Returns:
        The 0-based index in BASIS_LADDER, or None if not found.
    """
    try:
        return BASIS_LADDER.index(basis_set_name.lower())
    except ValueError:
        return None


def get_next_basis(basis_set_name: str) -> Optional[str]:
    """Gets the name of the next basis set in the ladder.

    Comparison is case-insensitive.

    Args:
        basis_set_name: The name of the current basis set.

    Returns:
        The name of the next basis set in the ladder, or None if the
        current basis is not found or is the last one.
    """
    current_rung = get_basis_rung(basis_set_name)
    if current_rung is None or current_rung + 1 >= len(BASIS_LADDER):
        return None
    return BASIS_LADDER[current_rung + 1]


def get_previous_basis(basis_set_name: str) -> Optional[str]:
    """Gets the name of the previous (smaller) basis set in the ladder.

    Comparison is case-insensitive.

    Args:
        basis_set_name: The name of the current basis set.

    Returns:
        The name of the previous basis set in the ladder, or None if the
        current basis is not found or is the first one.
    """
    current_rung = get_basis_rung(basis_set_name)
    if current_rung is None or current_rung == 0:
        return None # Not found or already at the smallest
    return BASIS_LADDER[current_rung - 1]


def get_basis_rung_original(basis_name: str) -> Optional[int]:
    """Get the rung index (0-based) of a basis set in the ladder.

    Args:
        basis_name: The name of the basis set.

    Returns:
        The index of the basis set in BASIS_LADDER, or None if not found.
    """
    try:
        return BASIS_LADDER.index(basis_name)
    except ValueError:
        return None


def get_next_basis_original(current_basis: str) -> Optional[str]:
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

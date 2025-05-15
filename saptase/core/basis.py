"""Basis set handling for SAPT calculations.

This module contains utilities for managing basis sets in SAPT calculations.
For the MVP, this is a minimal implementation with just the fixed jun-cc-pVDZ basis.
"""

from typing import Dict, List, Optional


# Internal helper for consistent string normalization
def _norm(name: str) -> str:
    return name.lower().strip()


# Default basis set for MVP
DEFAULT_BASIS = "jun-cc-pvdz"  # Remains lowercase as per convention

# Explicit mapping for density fitting basis sets (keys should be normalized)
DF_BASIS_MAP: Dict[str, str] = {
    _norm("cc-pvdz"): "cc-pvdz-jkfit",
    _norm("aug-cc-pvdz"): "aug-cc-pvdz-jkfit",
    _norm("cc-pvtz"): "cc-pvtz-jkfit",
    _norm("aug-cc-pvtz"): "aug-cc-pvtz-jkfit",
    _norm("jun-cc-pvdz"): "cc-pvdz-jkfit",  # jun- names are already normalized
    _norm("jun-cc-pvtz"): "cc-pvtz-jkfit",
    _norm("cc-pvqz"): "cc-pvqz-jkfit",
    _norm("aug-cc-pvqz"): "aug-cc-pvqz-jkfit",
    _norm("jun-cc-pvqz"): "cc-pvqz-jkfit",
    _norm("def2-svp"): "def2-universal-jkfit",
    _norm("def2-svpd"): "def2-universal-jkfit",
    _norm("def2-tzvp"): "def2-universal-jkfit",
    _norm("def2-tzvpd"): "def2-universal-jkfit",
    _norm("def2-tzvpp"): "def2-universal-jkfit",
    _norm("def2-tzvppd"): "def2-universal-jkfit",
    _norm("def2-qzvp"): "def2-universal-jkfit",
    _norm("def2-qzvpd"): "def2-universal-jkfit",
    _norm("def2-qzvpp"): "def2-universal-jkfit",
    _norm("def2-qzvppd"): "def2-universal-jkfit",
}

# Standard basis set ladder, ordered by increasing size/cost (should be normalized)
BASIS_LADDER: List[str] = [
    _norm("jun-cc-pvdz"),
    _norm("aug-cc-pvdz"),
    _norm("jun-cc-pvtz"),
    _norm("aug-cc-pvtz"),
    _norm("jun-cc-pvqz"),
    _norm("aug-cc-pvqz"),
]


def first_rung() -> str:
    """Returns the first basis set in the BASIS_LADDER."""
    return BASIS_LADDER[0]


# ---------- public helpers ----------


def get_df_basis(orbital_basis: str) -> str:
    """Get the corresponding density fitting basis set.

    Looks up in the explicit map first (case-insensitively and space-insensitively),
    then defaults to appending '-jkfit' to the normalized orbital basis name.

    Args:
        orbital_basis: The name of the orbital basis set.

    Returns:
        The name of the density fitting basis set.
    """
    lb = _norm(orbital_basis)
    # DF_BASIS_MAP keys are already normalized by _norm() at definition
    return DF_BASIS_MAP.get(lb, f"{lb}-jkfit")


def get_basis_rung(basis_set_name: str) -> Optional[int]:
    """Finds the index (rung) of a given basis set in the BASIS_LADDER.

    Comparison is case-insensitive and space-insensitive.

    Args:
        basis_set_name: The name of the basis set.

    Returns:
        The 0-based index in BASIS_LADDER, or None if not found.
    """
    try:
        # BASIS_LADDER elements are already normalized by _norm() at definition
        return BASIS_LADDER.index(_norm(basis_set_name))
    except ValueError:
        return None


def get_next_basis(basis_set_name: str, *, fallback_first: bool = False) -> Optional[str]:
    """Gets the name of the next basis set in the ladder.

    Comparison is case-insensitive and space-insensitive.

    Args:
        basis_set_name: The name of the current basis set.
        fallback_first: If True and basis_set_name is not found in the ladder,
                        return the first basis set from the ladder. Defaults to False.

    Returns:
        The name of the next basis set in the ladder, or the first basis if
        fallback_first is True and current basis is not found.
        Returns None if the current basis is not found (and fallback_first is False)
        or if it is the last one in the ladder.
    """
    idx = get_basis_rung(basis_set_name)  # Uses _norm internally
    if idx is None:
        return first_rung() if fallback_first else None

    if idx + 1 < len(BASIS_LADDER):
        return BASIS_LADDER[idx + 1]
    return None


def get_previous_basis(basis_set_name: str) -> Optional[str]:
    """Gets the name of the previous (smaller) basis set in the ladder.

    Comparison is case-insensitive and space-insensitive.

    Args:
        basis_set_name: The name of the current basis set.

    Returns:
        The name of the previous basis set in the ladder, or None if the
        current basis is not found or is the first one.
    """
    idx = get_basis_rung(basis_set_name)  # Uses _norm internally
    # Check if idx is not None (found) and greater than 0 (not the first element)
    return BASIS_LADDER[idx - 1] if idx is not None and idx > 0 else None

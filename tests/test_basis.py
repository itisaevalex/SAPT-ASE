# tests/test_basis.py
"""Tests for saptase.core.basis functions."""

import pytest
from saptase.core.basis import (
    BASIS_LADDER,
    get_basis_rung,
    get_next_basis,
    get_df_basis,
)


@pytest.mark.parametrize(
    "basis_name, expected_rung",
    [
        ("jun-cc-pvdz", 0),
        ("aug-cc-pVDZ", 1), # Case-insensitive check
        ("jun-cc-pvtz", 2),
        ("aug-cc-pVTZ", 3),
        ("non-existent-basis", None),
        (BASIS_LADDER[1], 1), # Test with direct value from list
    ]
)
def test_get_basis_rung(basis_name, expected_rung):
    """Test the get_basis_rung function."""
    assert get_basis_rung(basis_name) == expected_rung


@pytest.mark.parametrize(
    "current_basis, expected_next",
    [
        ("jun-cc-pvdz", "aug-cc-pvdz"),
        ("AUG-CC-PVDZ", "jun-cc-pvtz"), # Case-insensitive check
        ("jun-cc-pvtz", "aug-cc-pvtz"),
        ("aug-cc-pvtz", None), # Already at the top
        ("non-existent-basis", None), # Basis not found
        (BASIS_LADDER[0], BASIS_LADDER[1]), # Test with direct value from list
    ]
)
def test_get_next_basis(current_basis, expected_next):
    """Test the get_next_basis function."""
    assert get_next_basis(current_basis) == expected_next


@pytest.mark.parametrize(
    "orbital_basis, expected_df",
    [
        ("jun-cc-pvdz", "jun-cc-pvdz-jkfit"),
        ("aug-cc-pvdz", "aug-cc-pvdz-jkfit"),
        ("cc-pVTZ", "cc-pvtz-jkfit"), # Default mapping uses lowercase
        ("def2-svp", "def2-universal-jkfit"), # Explicit map entry
        ("def2-TZVPPD", "def2-universal-jkfit"), # Explicit map entry
        ("some-other-basis", "some-other-basis-jkfit"), # Default fallback
    ]
)
def test_get_df_basis(orbital_basis, expected_df):
    """Test the get_df_basis function."""
    assert get_df_basis(orbital_basis) == expected_df

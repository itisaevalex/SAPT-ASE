from saptase.core.basis import (
    BASIS_LADDER,
    get_basis_rung,
    get_df_basis,
    get_next_basis,
    get_previous_basis,
)


def test_basis_ladder_navigation():
    """Test navigation functions with the extended BASIS_LADDER."""
    assert (
        get_next_basis("aug-cc-pvtz") == "jun-cc-pvqz"
    ), "Next after aug-cc-pvtz should be jun-cc-pvqz"
    assert (
        get_next_basis("jun-cc-pvqz") == "aug-cc-pvqz"
    ), "Next after jun-cc-pvqz should be aug-cc-pvqz"
    assert get_next_basis("aug-cc-pvqz") is None, "Next after aug-cc-pvqz (top rung) should be None"

    assert (
        get_previous_basis("jun-cc-pvqz") == "aug-cc-pvtz"
    ), "Previous before jun-cc-pvqz should be aug-cc-pvtz"
    assert (
        get_previous_basis("aug-cc-pvdz") == "jun-cc-pvdz"
    ), "Previous before aug-cc-pvdz should be jun-cc-pvdz"
    assert (
        get_previous_basis("jun-cc-pvdz") is None
    ), "Previous before jun-cc-pvdz (bottom rung) should be None"

    # Test case-insensitivity as well
    assert get_next_basis("AUG-CC-PVTZ") == "jun-cc-pvqz"
    assert get_previous_basis("JUN-CC-PVQZ") == "aug-cc-pvtz"


def test_basis_rung_lookup():
    """Test get_basis_rung with the extended BASIS_LADDER."""
    assert get_basis_rung("jun-cc-pvdz") == 0
    assert get_basis_rung("aug-cc-pvdz") == 1
    assert get_basis_rung("jun-cc-pvtz") == 2
    assert get_basis_rung("aug-cc-pvtz") == 3
    assert get_basis_rung("jun-cc-pvqz") == 4
    assert get_basis_rung("aug-cc-pvqz") == 5

    assert get_basis_rung("AUG-CC-PVQZ") == 5  # Case-insensitivity
    assert get_basis_rung("non_existent_basis") is None


def test_df_basis_map_extensions():
    """Test that the DF_BASIS_MAP contains the new QZ entries."""
    assert get_df_basis("jun-cc-pvqz") == "cc-pvqz-jkfit"
    assert get_df_basis("aug-cc-pvqz") == "aug-cc-pvqz-jkfit"
    # Check one of the new def2 QZ entries
    assert get_df_basis("def2-qzvp") == "def2-universal-jkfit"
    assert get_df_basis("DEF2-QZVPPD") == "def2-universal-jkfit"  # Case insensitivity

    # Check a basis that defaults to -jkfit rule
    assert get_df_basis("cc-pv5z") == "cc-pv5z-jkfit"


def test_full_basis_ladder_content():
    """Verify the exact content and order of the BASIS_LADDER."""
    expected_ladder = [
        "jun-cc-pvdz",
        "aug-cc-pvdz",
        "jun-cc-pvtz",
        "aug-cc-pvtz",
        "jun-cc-pvqz",
        "aug-cc-pvqz",
    ]
    assert (
        BASIS_LADDER == expected_ladder
    ), f"BASIS_LADDER is {BASIS_LADDER}, expected {expected_ladder}"

from importlib import import_module

"""
Internal helper that loads Psi4 *and* all the symbols the backend needs,
no matter which Psi4 minor version is installed.

Other modules MUST NOT import psi4 directly; import from here instead.
"""

# Removed os, sys, tempfile, datetime imports as the complex logging is temporarily removed

# from types import ModuleType # Not strictly needed if only using for type hints in _first, which is now less complex

CANDIDATE_MODULES = [
    "psi4.core",
    "psi4.driver.exceptions",  # 1.7 fallback
    "psi4.driver.qcdb.exceptions",  # legacy fallback
]

PSI4_AVAILABLE = False
PSI4_IMPORT_ERROR = None  # populated if anything goes wrong
psi4 = None  # Ensure psi4 is defined in all paths

# Attempt to load psi4 and essential symbols
try:
    psi4_module_candidate = import_module("psi4")
    psi4 = psi4_module_candidate  # Assign to global psi4 if import succeeds
    PSI4_AVAILABLE = True
except Exception as exc:  # broad on purpose: importlib can raise a few
    PSI4_IMPORT_ERROR = exc
    # psi4 remains None


def _first(symbol: str, default: object = None) -> object:
    """Return the first occurrence of *symbol* in the candidate modules."""
    if not psi4:  # If psi4 module itself didn't load, don't bother searching candidates
        if default is not None:
            return default
        # If no default and psi4 didn't load, the symbol cannot be found.
        raise AttributeError(f"{symbol} could not be located because Psi4 module is not available")

    for mod_name in CANDIDATE_MODULES:
        try:
            # Attempt to import the specific submodule if it's not the main psi4 module
            if mod_name != "psi4":  # Should not happen with current CANDIDATE_MODULES
                mod_to_search = import_module(mod_name)
            else:
                mod_to_search = psi4  # Should already be imported

            return getattr(mod_to_search, symbol)
        except (ModuleNotFoundError, AttributeError):
            continue
    if default is not None:
        return default
    # If the symbol is not found in any candidate and no default is provided, raise an error.
    # This signals that a critical Psi4 component is missing even if Psi4 itself loaded.
    raise AttributeError(
        f"{symbol} could not be located in any candidate Psi4 module: {CANDIDATE_MODULES}"
    )


# Helper function to create dummy exception classes, replacing the lambda
def _create_fallback_exception(name: str) -> type:
    """Creates a new exception class with the given name."""
    return type(name, (Exception,), {})


if PSI4_AVAILABLE:  # Only try to define these if Psi4 itself loaded
    try:
        WavefunctionAlgorithmError = _first(
            "WavefunctionAlgorithmError", _create_fallback_exception("WavefunctionAlgorithmError")
        )
        BasisSetNotFound = _first(
            "BasisSetNotFound", _create_fallback_exception("BasisSetNotFound")
        )
        SCFConvergenceError = _first(
            "SCFConvergenceError", _create_fallback_exception("SCFConvergenceError")
        )
        Molecule = _first("Molecule", None)  # Psi4's Molecule class, fallback to None
    except (
        Exception
    ) as exc:  # ultra-defensive – should now be rare if _first handles missing symbols with defaults
        PSI4_AVAILABLE = False  # If symbol acquisition fails critically despite defaults in _first
        PSI4_IMPORT_ERROR = exc

# -------- guarantee the public symbols always exist (mock lane & fallback) --------
# This loop ensures that if PSI4_AVAILABLE was false, or became false above,
# these symbols still exist as None, so `from _psi4_compat import X` doesn't fail.
for _sym in (
    "WavefunctionAlgorithmError",
    "BasisSetNotFound",
    "SCFConvergenceError",
    "Molecule",  # Psi4's Molecule
):
    globals().setdefault(_sym, None)


__all__ = [
    "PSI4_AVAILABLE",
    "PSI4_IMPORT_ERROR",
    "BasisSetNotFound",
    "Molecule",  # This is Psi4's molecule
    "SCFConvergenceError",
    "WavefunctionAlgorithmError",
    "psi4",
]

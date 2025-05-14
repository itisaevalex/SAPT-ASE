"""
Internal helper that loads Psi4 *and* all the symbols the backend needs,
no matter which Psi4 minor version is installed.

Other modules MUST NOT import psi4 directly; import from here instead.
"""

from importlib import import_module

CANDIDATE_MODULES = [
    "psi4.core",
    "psi4.driver.exceptions",  # 1.7 fallback
    "psi4.driver.qcdb.exceptions",  # legacy fallback
]

PSI4_AVAILABLE = False
PSI4_IMPORT_ERROR = None  # populated if anything goes wrong

# Attempt to load psi4 and essential symbols
try:
    psi4 = import_module("psi4")
    PSI4_AVAILABLE = True
except Exception as exc:  # broad on purpose: importlib can raise a few
    PSI4_IMPORT_ERROR = exc
    psi4 = None  # type: ignore


def _first(symbol: str, default: object = None) -> object:
    """Return the first occurrence of *symbol* in the candidate modules."""
    if not psi4:  # If psi4 module itself didn't load, don't bother searching candidates
        if default is not None:
            return default
        raise AttributeError(f"{symbol} could not be located because Psi4 module is not available")

    for mod_name in CANDIDATE_MODULES:
        try:
            # Ensure the candidate module path is valid if it starts with 'psi4.'
            # For example, psi4.core needs the main psi4 to be loaded.
            if mod_name.startswith("psi4.") and not psi4:
                continue  # Skip if main psi4 isn't loaded

            # Attempt to import the specific submodule if it's not the main psi4 module
            if mod_name != "psi4":
                mod_to_search = import_module(mod_name)
            else:
                mod_to_search = psi4  # Should already be imported

            return getattr(mod_to_search, symbol)
        except (ModuleNotFoundError, AttributeError):
            continue
    if default is not None:
        return default
    raise AttributeError(f"{symbol} could not be located in any Psi4 module: {CANDIDATE_MODULES}")


if PSI4_AVAILABLE:
    try:
        WavefunctionAlgorithmError = _first("WavefunctionAlgorithmError")
        BasisSetNotFound = _first("BasisSetNotFound")
        SCFConvergenceError = _first("SCFConvergenceError")
        Molecule = _first("Molecule")  # This is Psi4's molecule class
    except AttributeError as exc:
        # Psi4 too old or mutilated → flag as unavailable
        PSI4_AVAILABLE = False
        PSI4_IMPORT_ERROR = exc

# Fallback definitions: Ensure the public symbols are defined even when Psi4 is absent or old.
# This allows `from ._psi4_compat import X, Y, Z` to always succeed in backend.py.
# The backend.py will then use `if X:` checks before actually using them.
if "WavefunctionAlgorithmError" not in globals():
    WavefunctionAlgorithmError = None  # type: ignore
if "BasisSetNotFound" not in globals():
    BasisSetNotFound = None  # type: ignore
if "SCFConvergenceError" not in globals():
    SCFConvergenceError = None  # type: ignore
if "Molecule" not in globals():  # This refers to Psi4's molecule
    Molecule = None  # type: ignore


__all__ = [
    "PSI4_AVAILABLE",
    "PSI4_IMPORT_ERROR",
    "BasisSetNotFound",
    "Molecule",  # This is Psi4's molecule
    "SCFConvergenceError",
    "WavefunctionAlgorithmError",
    "psi4",
]

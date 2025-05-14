"""
Internal helper that loads Psi4 *and* all the symbols the backend needs,
no matter which Psi4 minor version is installed.

Other modules MUST NOT import psi4 directly; import from here instead.
"""

from importlib import import_module
from types import ModuleType

CANDIDATE_MODULES = [
    "psi4.core",
    "psi4.driver.exceptions",  # 1.7 fallback
    "psi4.driver.qcdb.exceptions",  # legacy fallback
]

PSI4_AVAILABLE = False
PSI4_IMPORT_ERROR = None  # populated if anything goes wrong

try:
    psi4 = import_module("psi4")
    PSI4_AVAILABLE = True
except Exception as exc:  # broad on purpose: importlib can raise a few
    PSI4_IMPORT_ERROR = exc
    psi4 = None  # type: ignore


def _first(symbol: str, default: object = None) -> object:
    """Return the first occurrence of *symbol* in the candidate modules."""
    for mod_name in CANDIDATE_MODULES:
        try:
            mod: ModuleType = import_module(mod_name)
            return getattr(mod, symbol)
        except (ModuleNotFoundError, AttributeError):
            continue
    if default is not None:
        return default
    raise AttributeError(f"{symbol} could not be located in any Psi4 module")


if PSI4_AVAILABLE:
    try:
        WavefunctionAlgorithmError = _first("WavefunctionAlgorithmError")
        BasisSetNotFound = _first("BasisSetNotFound")
        SCFConvergenceError = _first("SCFConvergenceError")
        Molecule = _first("Molecule")
    except AttributeError as exc:
        # Psi4 too old or mutilated → flag as unavailable
        PSI4_AVAILABLE = False
        PSI4_IMPORT_ERROR = exc

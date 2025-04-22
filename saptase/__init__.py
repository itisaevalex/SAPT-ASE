"""SAPTASE: Automated multi-fidelity SAPT(DFT) workflows."""

__version__ = "0.1.0"

# Expose core components
from .core.orchestrator import SaptWorkflow
from .core.models import SaptTask, TaskStatus, Molecule, SaptResult
from .core.errors import SaptError # Keep existing error exports if used
from .core.backend import SaptBackend, Psi4Backend # Optional: if users need direct access
from .core.basis import BASIS_LADDER # Expose basis set ladder

# Make version easily accessible
__all__ = [
    "SaptWorkflow",
    "SaptTask",
    "TaskStatus",
    "Molecule",
    "SaptResult",
    "SaptError",
    "SaptBackend",
    "Psi4Backend",
    "BASIS_LADDER",
    "__version__",
]

"""SAPTASE: Automated multi-fidelity SAPT(DFT) workflows."""

__version__ = "0.1.0"

# Expose core components
from .core.backend import Psi4Backend, SaptBackend  # Optional: if users need direct access
from .core.basis import BASIS_LADDER  # Expose basis set ladder
from .core.errors import SaptError  # Keep existing error exports if used
from .core.models import Molecule, SaptResult, SaptTask, TaskStatus
from .core.orchestrator import SaptWorkflow

# Make version easily accessible
__all__ = [
    "BASIS_LADDER",
    "Molecule",
    "Psi4Backend",
    "SaptBackend",
    "SaptError",
    "SaptResult",
    "SaptTask",
    "SaptWorkflow",
    "TaskStatus",
    "__version__",
]

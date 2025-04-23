# saptase/core/errors.py
"""Custom exception types for the saptase workflow."""


class SaptError(Exception):
    """Base class for saptase specific errors."""

    def __init__(self, message: str, original_exception: Exception | None = None):
        super().__init__(message)
        self.original_exception = original_exception


class ScfFailed(SaptError):
    """Raised when the SCF procedure fails to converge."""

    pass


class BasisIncompatible(SaptError):
    """Raised when there is an issue with the basis set specification or compatibility."""

    pass


class MemoryExceeded(SaptError):
    """Raised when a calculation fails due to insufficient memory."""

    pass


class PsiProgramCrashed(SaptError):
    """Raised for generic Psi4 core exceptions or crashes."""

    pass


# Future exceptions (placeholders)
class InputError(SaptError):
    """Raised for errors in the input geometry or task specification."""

    pass


class ResourceLimitExceeded(SaptError):
    """Raised when a calculation exceeds resource limits (e.g., wall time, disk)."""

    pass

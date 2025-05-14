# ADR-0007: Optional Psi4 Integration and Robustness

**Date:** 2025-05-15
**Status:** Implemented

## Context and Problem Statement

SAPTASE aims to optionally use the Psi4 quantum chemistry package as a backend for SAPT calculations. Initial development faced several challenges:

1.  **Hard Dependency:** Direct imports of `psi4` and its submodules (e.g., `psi4.core`, `psi4.driver.exceptions`) in core library code (`saptase.core.backend`) created a hard dependency. This made it difficult to run `saptase` or its tests in environments without a full Psi4 installation, even for functionalities not directly requiring Psi4 (e.g., workflow orchestration logic, mock tests).
2.  **CI Complexity:** Mocking Psi4 effectively in CI for different test scenarios (unit tests, integration tests without Psi4) proved difficult, leading to `ModuleNotFoundError` or `AttributeError` exceptions.
3.  **Platform-Specific Failures:** Test suites, particularly those involving mocks and import-time checks for Psi4, exhibited platform-specific failures (e.g., on Windows), often due to subtle differences in import machinery or module introspection.
4.  **Psi4 API Variations:** Different Psi4 versions might have slight variations in where specific exception classes or components are located, or how they are instantiated (e.g., `psi4.core.Molecule` creation).

The goal was to make Psi4 a truly optional dependency, allow `saptase` to function gracefully (or with clear error messages) when Psi4 is missing or incomplete, and ensure CI stability across all platforms and test modes.

## Decision Drivers

*   Desire to run parts of `saptase` (like CLI parsing, workflow setup, basic models) without requiring a full Psi4 installation.
*   Need for reliable and consistent testing in CI, including dedicated "mock" lanes that do not install or use Psi4.
*   Requirement for the codebase to be robust against missing Psi4 components or minor API variations.
*   Need to eliminate platform-specific test failures.

## Considered Options

1.  **Scattered Conditional Imports:** Placing `try-except ImportError` blocks around every Psi4 import in `saptase.core.backend.py` and other files. This would be verbose, error-prone, and hard to maintain.
2.  **Global `PSI4_AVAILABLE` Flag with Basic Mocks:** Using a global flag set at import time and then using basic `MagicMock` objects for Psi4 components if the flag was false. This proved insufficient for more complex interactions and exception handling.
3.  **Centralized Compatibility Layer (Chosen):** Create a dedicated module to handle all Psi4 imports, provide fallbacks for missing components, and abstract away version differences.

## Decision Outcome

Chosen Option: **Centralized Compatibility Layer and Enhanced Mocking**

This solution involves several key components:

1.  **`saptase.core._psi4_compat.py` Module:**
    *   **Purpose:** Acts as the single point of truth for importing Psi4 and its components.
    *   **Mechanism:**
        *   It attempts to import `psi4`.
        *   If successful, it then tries to find specific symbols (e.g., `WavefunctionAlgorithmError`, `BasisSetNotFound`, `SCFConvergenceError`, `Molecule`) by looking in a predefined list of `CANDIDATE_MODULES` (e.g., `psi4.core`, `psi4.driver.exceptions`, `psi4.driver.qcdb.exceptions`). This provides resilience against Psi4 internal restructuring.
        *   **Fallbacks:**
            *   If a specific exception class (e.g., `SCFConvergenceError`) isn't found, it dynamically creates a unique, lightweight `Exception` subclass (e.g., `SCFConvergenceErrorFallbackExc(SaptError)`). This ensures that `except SpecificPsi4Error:` clauses in the backend can still function predictably even if the real Psi4 error isn't available.
            *   If `psi4.core.Molecule` isn't found, it defaults to `None`.
            *   If the main `psi4` module itself cannot be imported, `PSI4_AVAILABLE` is set to `False`, and all Psi4-related symbols from this module resolve to their fallbacks (e.g., `None` or the fallback exception types).
        *   **Guaranteed Symbols:** All public symbols intended for import from `_psi4_compat.py` are guaranteed to be defined (e.g., using `globals().setdefault(_sym, None)`), preventing `ImportError` when `saptase.core.backend.py` imports from it.
    *   **Usage:** `saptase.core.backend.py` (and any other module needing Psi4 components) now *only* imports them from `saptase.core._psi4_compat.py`.

2.  **Enhanced Mocking in `tests/conftest.py`:**
    *   **Early Mocking:** `conftest.py` now proactively inserts mock `psi4` and `psi4.core` modules into `sys.modules` *before* most other imports occur. These mocks are `types.ModuleType` instances.
    *   **Populating Mocks:** These mock modules are populated with mock versions of the specific exceptions and classes (e.g., `MockWavefunctionAlgorithmError = type("MockWavefunctionAlgorithmError", (Exception,), {})`) that `_psi4_compat.py` will attempt to find. This ensures that in a mock testing environment, `_psi4_compat.py` finds these mocks and reports `PSI4_AVAILABLE = True` (if the top-level `psi4` mock is found), allowing tests of logic that depends on these symbols to proceed.
    *   **`__spec__` Attribute:** Crucially, for the mock `psi4` and `psi4.core` modules, the `__spec__` attribute is explicitly set using `importlib.machinery.ModuleSpec("module_name", loader=None)`. This resolved Windows-specific CI failures where `importlib.util.find_spec("psi4")` would raise `ValueError: psi4.__spec__ is None`.

3.  **Robust Exception Handling in `saptase.core.backend.py`:**
    *   A `_safe_exc(obj, fallback)` helper function was introduced. It checks if `obj` (typically a symbol imported from `_psi4_compat.py` that *should* be an exception) is indeed a subclass of `BaseException`. If not (e.g., if it resolved to `None` or a non-exception mock), it returns the `fallback` exception type (usually `SaptError`).
    *   This is used to define aliases like `PsiValidationError = _safe_exc(_psi4_compat.ValidationError, SaptError)`. `except` clauses then use these safe aliases (e.g., `except PsiValidationError:`), preventing `TypeError` if a Psi4 exception was mocked incorrectly as a non-exception type.

4.  **Correct API Usage:**
    *   Ensured correct Psi4 API usage, for example, changing molecule creation from an incorrect constructor call on `psi4.core.Molecule` to `psi4.geometry(molecule_xyz_string)`.

## Consequences

*   **Improved Robustness:** `saptase` can now be imported and run (for non-Psi4 tasks) even if Psi4 is not installed or is incomplete. Core logic that interacts with Psi4 symbols handles their potential absence gracefully.
*   **CI Stability:** CI tests are now stable across all platforms (Linux, macOS, Windows) and in both "mock" and "real Psi4" modes. The `__spec__` fix was key for Windows stability.
*   **Clearer Separation:** The `_psi4_compat.py` module provides a clean separation of concerns for Psi4 interaction.
*   **Testability:** The enhanced mocking strategy in `conftest.py` allows `_psi4_compat.py` and dependent modules like `backend.py` to be tested more thoroughly in mock environments.
*   **Developer Experience:** Reduced friction from unexpected import errors or platform-specific test failures related to Psi4.

## Link to Implementation

This approach was implemented through a series of commits, culminating around May 14-15, 2025. Key files involved:

*   `saptase/core/_psi4_compat.py` (new file)
*   `saptase/core/backend.py` (significant refactoring of imports and exception handling)
*   `tests/conftest.py` (major updates to Psi4 mocking)
*   `tests/test_backend.py` (updates to align mock exceptions with `_psi4_compat`)
*   `.github/workflows/ci.yml` (iterative improvements to test execution) 
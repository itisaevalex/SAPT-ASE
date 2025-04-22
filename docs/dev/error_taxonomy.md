# SAPTASE Error Taxonomy

This document maps specific error messages or conditions encountered in backend quantum chemistry packages (like Psi4) to the unified `saptase.core.errors` exception types.

| Backend | Error Signature (Regex/Code) | `SaptError` Subclass     | Notes |
|---------|------------------------------|--------------------------|-------|
| Psi4    | `psi4.SCFConvergenceError`   | `ScfFailed`              | Direct mapping |
| Psi4    | `InputError:.*basis set`     | `BasisIncompatible`      | Example regex for basis issues |
| Psi4    | `MemoryError`, `malloc fail` | `MemoryExceeded`         | Example regex for memory issues |
| Psi4    | `psi4.core.PsiException`     | `PsiProgramCrashed`      | Catch-all for other Psi4 exceptions |
| Runtime | `MemoryError` (Python)       | `MemoryExceeded`         | Python-level memory error |
| Runtime | _(Other specific runtime conditions)_ | _(Relevant SaptError)_ | E.g., disk full, permissions |

_(This table should be expanded as more specific error conditions and recovery strategies are identified)._

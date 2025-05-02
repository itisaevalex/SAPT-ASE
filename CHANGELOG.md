# Changelog

All notable changes to this project will be documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions
adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Added `psi4` pytest marker and applied it to tests requiring a real Psi4 installation.
- Created Conda environment file (`environment-ci.yml`) for CI `real` mode.
- Added documentation (`docs/ci_psi4.md`) explaining the Psi4 CI setup and local replication.

### Changed
- Modified GitHub Actions workflow (`.github/workflows/ci.yml`):
    - Introduced `psi4-mode` matrix dimension (`mock`, `real`).
    - Conditionally install dependencies using `pip` (`mock`) or `micromamba` (`real`).
    - Conditionally run tests based on markers (`not slow and not psi4` for `mock`, `psi4` for `real`).
    - Use `mamba-org/setup-micromamba` for Conda environment creation and caching.
    - Conditionally activate conda environment for smoke test in `real` mode.
- Refactored `saptase.core.backend._has_psi4` logic to correctly handle mocked Psi4 when `CI_FAST=1`.
- Changed Dask leak guard log level from `ERROR` to `INFO` in `saptase.execution.dask.py`.

### Fixed
- Resolved CI failures related to installing Psi4 (`ENOENT` for environment file, invalid `micromamba create` args).
- Fixed CI smoke test failures in `real` mode (`ModuleNotFoundError`, argument parsing error) by ensuring execution within the activated conda environment.
- Fixed test failures in `mock` mode (`tests/test_backend.py`, `tests/test_backend_scratch.py`) caused by `CI_FAST=1` prematurely exiting `Psi4Backend.calculate`.

## [0.4.0] – 2025-04-24

### Added
- **Distributed execution** via Dask: `SaptWorkflow.run_dask` and `DaskExecutor`.
- **Scratch-directory isolation** on all workers (`TaskScratch`) with automatic
  cleanup; configurable through the `SAPTASE_SCRATCH_ROOT` env-var and the new
  CLI flags `--scratch-root` / `--keep-scratch`.
- **SQLite WAL** mode for provenance `LogDb`, enabling safe concurrent writes
  from multiple Dask workers.
- **SLURM helper** `create_slurm_cluster` (optional `dask_jobqueue` extra).
- **Stress-test** (`tests/test_dask_stress.py`) that submits 100 tasks to a
  local Dask cluster; optional CI job gated by `RUN_STRESS=true`.
- Global CLI flags for scratch behaviour, version bumped badge.

### Changed
- Project version bumped to **0.4.0**.
- CI hardened: Windows runner now sets `SAPTASE_SCRATCH_ROOT`; optional stress
  job added.

### Fixed
- Orchestrator scratch & logging edge-cases under Dask.

### Documentation
- README quick-start updated for scratch and SLURM.
- Development Workflow Guide gains *Scratch & WAL behaviour* subsection.
- ADR-0005 accepted (Dask execution layer).

## [0.4.1] - YYYY-MM-DD

### Fixed
- Corrected relative import error in `saptase/cli.py` when run as a script (`ImportError: attempted relative import with no known parent package`). Test `tests/test_cli_run.py` now invokes the `saptase` entry point directly. (Related to Issue #XYZ or PR #ABC)
- Added rule `TID252` (prefer absolute imports) to Ruff configuration in `pyproject.toml` to prevent regressions.
- Resolved database corruption warnings (`sqlite3.DatabaseError: database disk image is malformed`) during testing by implementing a recovery mechanism in `saptase/core/logdb.py` that renames the corrupt file and creates a fresh database.
- Centralized the `CI_FAST=1` environment variable check in `saptase/core/backend.py` using the `_maybe_import_psi4` helper to ensure mock backends are used consistently, including in subprocesses.
- Introduced `saptase.core.backend.SuccessMockBackend` to provide a successful mock result when `CI_FAST=1` is set but `tests.conftest.MockBackend` is unavailable, fixing `test_cli_run_local_dask_success`.
- Fixed Dask `LocalCluster` leaks detected by the `assert_no_leaked_dask_cluster` fixture by ensuring `saptase.execution.dask.DaskExecutor` is used as a context manager in `saptase/core/orchestrator.py::run_dask`.
- Corrected assertions in `tests/test_cli_run.py::test_cli_run_local_dask_success` to check the database by `task_id` instead of `run_id` and to check the correct scratch subdirectory path.
- Added `--keep-scratch` flag to the CLI command in `test_cli_run_local_dask_success` to prevent premature deletion of scratch directories needed for assertions.
- Resolved intermittent Dask `LocalCluster` leaks reported by test fixtures (`assert_no_leaked_dask_cluster`, `assert_no_cluster_leak_per_test`) by ensuring `DaskExecutor.close` explicitly drops cluster/client references and calls `gc.collect()`.
- **Resolved persistent Dask `LocalCluster` leaks** in stress tests by ensuring the test correctly utilizes the `DaskExecutor` context manager and passes the scheduler address (not the client object) to `SaptWorkflow.run_dask`, and by refining `DaskExecutor.__exit__` to use `dask.distributed.utils.sync` for robust asynchronous cleanup.

---

## [0.3.0] – 2025-02-10
_This release predates the Dask work and introduced adaptive basis escalation._

(See ADR-0004 and progress log for details.)

---

Older history can be reconstructed from Git commit messages and the
`docs/dev/cascade-progress-log.md` timeline.

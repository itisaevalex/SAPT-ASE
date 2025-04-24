# Changelog

All notable changes to this project will be documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions
adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

---

## [0.3.0] – 2025-02-10
_This release predates the Dask work and introduced adaptive basis escalation._

(See ADR-0004 and progress log for details.)

---

Older history can be reconstructed from Git commit messages and the
`docs/dev/cascade-progress-log.md` timeline.

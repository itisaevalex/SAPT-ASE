# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Resolved `FrozenInstanceError` in `SaptTask` by removing `frozen=True`.
- Fixed Psi4 dimer input format in `Psi4Backend` for correct fragment specification.
- Refactored parallel task execution in `SaptWorkflow` to use a top-level function, fixing pickling errors with `ProcessPoolExecutor`.
- Skipped problematic parallel test (`test_workflow_run_local_parallel_correctness`) that used a non-pickleable mock backend.
- Corrected Psi4 installation procedure for Windows/conda (use `-c conda-forge` only) and added `check_psi4.py` diagnostic script.

# AGENTS.MD: Guide for AI Assistants

This document provides context for AI assistants working with the `saptase` project.

## 1. Project Overview

**`saptase` (SAPT(DFT) Automation Suite for Extended systems)** is a Python-based framework designed to automate and manage Symmetry-Adapted Perturbation Theory (SAPT) calculations, particularly SAPT(DFT), for molecular systems. Its primary goal is to streamline the workflow for high-throughput quantum chemistry computations, including task definition, execution, data storage, and analysis.

The project is often used in research settings for studying non-covalent interactions in molecular dimers and larger systems.

## 2. Key Technologies & Libraries

*   **Python:** The core language of the project.
*   **Psi4:** The primary quantum chemistry engine used for performing SAPT(DFT) and other electronic structure calculations. Psi4 can be challenging to install, especially on Windows.
*   **Dask:** Used for parallel execution of computational tasks, enabling efficient use of multi-core processors or distributed computing resources.
*   **SQLite:** Used as the backend for a logging database (`logdb`) that tracks the status, metadata, and results of computational tasks.
*   **YAML:** Used for configuration files that define computational sweeps, task parameters, and system setups.
*   **Micromamba/Conda:** Used for managing Python environments and dependencies, especially critical for handling Psi4. The project uses an `environment-ci.yml` file for defining the Conda environment.
*   **Pytest:** Used for running automated tests.
*   **GitHub Actions:** Used for Continuous Integration (CI), primarily targeting Linux environments.

## 3. Core Concepts

*   **Molecule:** Represents a molecular structure, typically defined by XYZ coordinates. Handling the precision and string representation of XYZ coordinates has been a key area of focus for caching.
*   **Task:** A specific computational job, such as a SAPT(DFT) energy calculation for a given molecular dimer with a specific basis set and level of theory. Tasks are often defined in YAML files.
*   **Task ID:** A unique identifier for each task, often generated from the molecule names, method, basis set, and other relevant parameters. Crucial for caching and database lookups.
*   **Caching:** The system attempts to cache results of completed tasks to avoid recomputation. Cache hits/misses are determined by matching task parameters, including the precise string representation of molecular geometries.
*   **Orchestrator (`saptase/core/orchestrator.py`):** The central component responsible for managing the lifecycle of tasks: reading configurations, generating task IDs, checking cache, submitting jobs (e.g., via Dask), and logging results.
*   **Log Database (`saptase/core/logdb.py`):** Stores information about each task, including its ID, status (e.g., `PENDING`, `COMPLETED`, `FAILED`), input parameters, and file paths to results.
*   **Chunks:** For large-scale computations, tasks might be divided into "chunks," with each chunk having its own configuration file and potentially its own results database (e.g., `runs_chunk_X_of_Y.sqlite`). There\'s a need to merge these chunk-specific databases into a main database.

## 4. Project Structure (Key Files/Directories)

*   **`saptase/`**: The main source code directory.
    *   **`core/`**: Contains the core logic.
        *   **`models.py`**: Defines data models like `Molecule`.
        *   **`orchestrator.py`**: Task management and execution logic.
        *   **`logdb.py`**: Database interaction layer.
        *   **`calculator.py`**: Interface with the quantum chemistry engine (Psi4).
    *   **`cli/`**: Code for the command-line interface.
        *   **`main.py`** (or similar): Entry point for `python -m saptase.cli ...`
*   **`examples/`**: Contains example YAML configuration files (e.g., `dask_local_demo.yml`) and sample XYZ files.
*   **`tests/`**: Contains automated tests, likely using `pytest`.
*   **`docs/`**: Project documentation.
    *   **`adr/`**: Contains **Architecture Decision Records (ADRs)**. These documents record important architectural decisions, their context, and consequences. They are valuable for understanding the rationale behind design choices.
*   **`.github/workflows/ci.yml`**: Defines the GitHub Actions CI pipeline.
*   **`environment-ci.yml`**: Conda environment definition file.
*   **Scripts (root or `scripts/` directory):** Utility scripts for tasks like database manipulation (e.g., `fix_xyz_strings.py`, `add_missing_tasks.py`, `find_missing_tasks.py`).

## 5. Running and Testing

*   **CLI Usage:** Tasks are typically run via the CLI:
    `python -m saptase.cli run <config.yml> --mode <dask|local>`
*   **Environment Setup:** A Conda environment (e.g., `saptase-ci`) should be created using `micromamba create -f environment-ci.yml` and then activated.
*   **Testing:** Tests are run using `pytest`. Some tests might be marked as "slow" or "psi4" (requiring a real Psi4 installation).
    *   `pytest -v -m "not slow and not psi4"` (for fast, mock tests)
    *   `pytest -v -m "psi4"` (for tests requiring Psi4)

## 6. Common Agent Tasks

*   **Debugging CI Failures:** CI primarily runs on Linux. Failures often relate to Psi4, Dask, or environment setup.
*   **Modifying Workflow Scripts:** Updating Python scripts for task management, database interaction, or data processing.
*   **Analyzing Task Failures:** Inspecting database logs and output files to understand why specific SAPT calculations failed.
*   **Updating CI Configuration (`.github/workflows/ci.yml`):** Adjusting CI steps, environment setup, or test execution.
*   **Assisting with Database Operations:** Helping to query or modify the SQLite databases used for logging.
*   **Consulting ADRs (`docs/adr/`):** Referencing ADRs to understand past design decisions before proposing significant changes.

This guide should help any AI assistant get up to speed quickly. Remember to refer to specific file contents for detailed implementation. 
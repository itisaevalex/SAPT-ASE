# Running Real Psi4 CI Tests

This document explains how to run the CI tests that require a real Psi4 installation, both locally and how they function within the GitHub Actions workflow.

## GitHub Actions Workflow

The main CI workflow (`.github/workflows/ci.yml`) uses a matrix strategy to run tests in two modes:

1.  **`mock` mode:** Uses standard `pip` to install dependencies (no Psi4) and runs fast tests (`pytest -m "not slow and not psi4"`). The `CI_FAST=1` environment variable ensures code uses mock backends.
2.  **`real` mode:** Uses `micromamba` to create a Conda environment (`env/ci.yml`) containing `psi4` and `pytest`. It then installs the `saptase` package editable into this environment and runs the slow tests requiring Psi4 (`pytest -m "slow and psi4"`).

### Caching

The `mamba-org/setup-micromamba@v1` action automatically caches the downloaded Conda packages (`cache-downloads: true`). This significantly speeds up subsequent runs after the first time the environment is created.

If you need to force a cache refresh (e.g., after updating the `psi4` version pin in `env/ci.yml`), you can manually delete the cache entry in the GitHub repository settings under "Actions -> Caches". The cache key typically includes a hash of the environment file, so changing the file often busts the cache automatically.

## Running Locally with Micromamba

You can replicate the `real` mode environment locally using Micromamba (or Mamba/Conda).

1.  **Install Micromamba:** Follow the instructions at [https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html](https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html)

2.  **Create the environment:** Navigate to the project root directory and run:
    ```bash
    micromamba create -f env/ci.yml -y
    ```
    This creates a new environment named `saptase-ci` (as defined in `env/ci.yml`).

3.  **Activate the environment:**
    ```bash
    micromamba activate saptase-ci
    ```

4.  **Install SAPT-ASE editable:**
    ```bash
    pip install -e .
    ```

5.  **Run the Psi4 tests:**
    ```bash
    pytest -v -m "slow and psi4"
    ```

This setup allows you to debug and verify the Psi4-dependent tests in the same environment used by the CI `real` mode. 
# SAPTASE: Automated Multi-Fidelity SAPT(DFT) Workflows
![version](https://img.shields.io/badge/version-0.4.1--dev-blue)

SAPTASE (Symmetry-Adapted Perturbation Theory Automated Simulation Engine) is a Python framework designed to streamline and automate complex computational chemistry workflows involving SAPT calculations. It emphasizes robustness, flexibility, and scalability for high-throughput studies.

## Key Features

*   **Versatile Workflow Orchestration:** Define and manage collections of SAPT calculations, from single-point energies to complex multi-step procedures.
*   **Multiple Execution Modes:**
    *   Local sequential execution for simple tasks.
    *   Local parallel execution leveraging multiple cores on a single machine (via `ProcessPoolExecutor`).
    *   Distributed execution across HPC clusters using Dask, with support for SLURM.
*   **Optional Psi4 Integration with Robust Fallbacks:**
    *   Primarily uses Psi4 as the computational backend for SAPT calculations.
    *   Can be installed and run even if Psi4 is not present; core workflow and data model functionalities remain available.
    *   Gracefully handles missing Psi4 components or minor API variations through a dedicated compatibility layer (`saptase.core._psi4_compat`).
*   **Advanced Calculation Strategies:**
    *   **Adaptive Basis Set Escalation:** Automatically find an optimal basis set level by iteratively increasing basis set size based on user-defined energy convergence criteria.
    *   **Error Recovery:** Built-in mechanisms to automatically attempt recovery from common calculation failures (e.g., SCF convergence issues in Psi4) using a predefined ladder of strategies.
*   **Provenance and Reproducibility:**
    *   Detailed logging of all calculation attempts, including retries and errors, to an SQLite database for comprehensive provenance.
    *   Controlled scratch directory management for organized and reproducible calculations.
*   **Specialized Workflows:** Facilitates large-scale benchmark calculations, such as "Pauling-point" sweeps for datasets like S22, through helper scripts for task generation.
*   **Extensible Backend System:** Designed with an abstract backend interface (`SaptBackend`) to potentially support other quantum chemistry packages like CamCASP or SAPT2020 in the future.

## Installation

### Prerequisites
- Python 3.10+
- NumPy

### General Installation
SAPTASE can be installed from PyPI (once available) or directly from source.

```bash
# Clone the repository (if installing from source)
git clone https://github.com/yourusername/saptase.git # Replace with actual URL
cd saptase

# Create and activate a Conda environment (recommended)
conda create -n saptase-env python=3.10 numpy pytest
conda activate saptase-env

# Install SAPTASE
pip install -e .[dev] # For an editable install with development dependencies
# or
# pip install . # For a standard install
```

##### CLI Command Reference

- `saptase run <job.yml>` – run a standard workflow defined in a YAML/JSON file.
- `saptase run-adaptive <config.yml>` – execute an adaptive basis escalation workflow.
- `saptase results <run_id>` – fetch and display results from the provenance database.
- `saptase db <deduplicate|delete-failed|vacuum|merge>` – manage the SQLite log database.

Global options such as `--scratch-root` and `--keep-scratch` may be supplied before the subcommand to override scratch directory handling.

The CLI also provides database management utilities under the `db` subcommand:
```bash
# Vacuum the default database (runs/saptase_provenance.sqlite)
saptase db vacuum

# Vacuum a specific database
saptase db vacuum --db-path my_workflow.sqlite

# Delete failed tasks from a specific database
saptase db delete-failed --db-path my_workflow.sqlite

# Deduplicate tasks in a specific database (keeps oldest successful by default)
saptase db deduplicate --db-path my_workflow.sqlite

# Deduplicate tasks, keeping the newest successful record if duplicates are found
saptase db deduplicate --db-path my_workflow.sqlite --overwrite

# Merge entries from a chunk database into the main database
saptase db merge --source-db chunk2.sqlite --db-path my_workflow.sqlite
```


### Installing with Psi4 (Optional Backend)
Psi4 is the primary supported quantum chemistry backend.
If you intend to run calculations:

1.  **Install Psi4:** The recommended way is via Conda:
    ```bash
    conda install -c psi4 psi4
    ```
    Ensure Psi4 is installed within the same environment as SAPTASE. Refer to the official [Psi4 installation guide](https://psicode.org/psi4manual/master/conda.html) for the latest instructions.

2.  **Reference CI Environment:** For a known-good environment with Psi4 and SAPTASE dependencies, you can refer to `environment-ci.yml` used in our GitHub Actions.

SAPTASE can be installed and used for workflow management and other tasks even if Psi4 is not available. Features requiring Psi4 will attempt to use it and report errors if it's not found or configured correctly.

## Core Concepts

SAPTASE's architecture revolves around a few key components:

*   **`Molecule`**: Represents a molecular structure. Can be created from XYZ files or strings.
    ```python
    from saptase.core.models import Molecule
    mol = Molecule.from_xyz_string("2\nHelium Dimer\nHe 0 0 0\nHe 0 0 3")
    ```
*   **`SaptTask`**: Defines a single SAPT calculation, including the two monomer `Molecule` objects, basis set, method, and any additional keywords for the backend.
    ```python
    from saptase.core.models import SaptTask
    task = SaptTask(monomer_a=mol_a, monomer_b=mol_b, basis_set="jun-cc-pVDZ", method="sapt0")
    ```
*   **`SaptResult`**: Stores the outcome of a `SaptTask`, including energy components, success status, and error messages.
*   **`SaptBackend`**: An abstract interface for computational backends. `Psi4Backend` is the primary implementation.
*   **`SaptWorkflow`**: Manages a collection of `SaptTask` objects and orchestrates their execution.
    ```python
    from saptase.core.orchestrator import SaptWorkflow
    workflow = SaptWorkflow()
    workflow.add_task(task1)
    workflow.add_dimer(mol_c, mol_d, basis_set="aug-cc-pVTZ") # Convenience method
    ```

## Usage Examples

### 1. Single SAPT Calculation

For a quick, single calculation, use the `run_sapt` convenience function:

```python
from saptase.core.models import Molecule
from saptase.core.orchestrator import run_sapt

# Define water monomers (example XYZ strings)
water_a_xyz = "3\nWater A\nO -1.551007 -0.114520 0.0\nH -1.934259  0.762503 0.0\nH -0.599677  0.040712 0.0"
water_b_xyz = "3\nWater B\nO  1.350625  0.111469 0.0\nH  1.680398 -0.373741 -0.758561\nH  1.680398 -0.373741  0.758561"

monomer_a = Molecule.from_xyz_string(water_a_xyz, name="WaterA")
monomer_b = Molecule.from_xyz_string(water_b_xyz, name="WaterB")

# Run SAPT0 calculation using Psi4 backend (if installed)
result = run_sapt(monomer_a, monomer_b, basis_set="jun-cc-pVDZ", method="sapt0")

if result.success:
    print(f"Total interaction energy: {result.total_energy:.8f} Hartree")
    print(f"                          {result.total_energy_kcal_mol():.4f} kcal/mol")
    print("Components (Hartree):")
    for component, energy in result.energies.items():
        print(f"  {component}: {energy:.8f}")
else:
    print(f"Calculation failed: {result.error_message}")
```

### 2. Managing Multiple Tasks with `SaptWorkflow`

#### a) Local Sequential Execution

```python
workflow = SaptWorkflow()
# Add multiple tasks (task1, task2, ...)
# ...
results_dict = workflow.run_local_serial() # Returns a dict of task_id: SaptResult
for task_id, result in results_dict.items():
    if result.success:
        print(f"Task {task_id} success. Total Energy: {result.total_energy_kcal_mol():.4f} kcal/mol")
```

#### b) Local Parallel Execution (Multiple Cores)

```python
# workflow defined as above
results_dict = workflow.run_local_parallel(max_workers=4) # Uses 4 worker processes
# Process results_dict as above
```
Note: `OMP_NUM_THREADS` is automatically managed for Psi4 within workers.

### 3. Distributed Execution with Dask

SAPTASE can distribute tasks using Dask, either to a local Dask cluster or a cluster managed by SLURM, LSF, etc. (via `dask-jobqueue`).

#### a) Using the Command-Line Interface (CLI)

The `saptase` CLI is useful for running predefined task collections from a YAML file.

```bash
# Example: run tasks defined in job.yml using a local Dask cluster with 4 workers
# Scratch files go into /tmp/saptase_scratch and are kept after completion.
# Results are stored in a database named my_workflow.sqlite in the current directory.
export SAPTASE_SCRATCH_ROOT=/tmp/saptase_scratch
saptase run job.yml --mode dask --workers 4 --keep-scratch --db-path my_workflow.sqlite

# Example: Submit to an existing Dask scheduler
# saptase run job.yml --mode dask --scheduler tcp://your-scheduler-address:8786

# Example: Limit workers for tasks with large basis sets (experimental)
# saptase run job.yml --mode local_parallel --max-workers-big-basis 2
```
An example `job.yml` can be found in the `examples/` directory.

The CLI also provides database management utilities under the `db` subcommand:
```bash
# Vacuum the default database (runs/saptase_provenance.sqlite)
saptase db vacuum

# Vacuum a specific database
saptase db vacuum --db-path my_workflow.sqlite

# Delete failed tasks from a specific database
saptase db delete-failed --db-path my_workflow.sqlite

# Deduplicate tasks in a specific database (keeps oldest successful by default)
saptase db deduplicate --db-path my_workflow.sqlite

# Deduplicate tasks, keeping the newest successful record if duplicates are found
saptase db deduplicate --db-path my_workflow.sqlite --overwrite
```

#### b) Programmatic Dask Execution (e.g., with SLURM)

First, install the `dask_jobqueue` extra: `pip install "saptase[dask_jobqueue]"`

```python
from saptase.execution.slurm import create_slurm_cluster
from saptase.core.orchestrator import SaptWorkflow
# Define workflow and add tasks...

# Example: Create a SLURM cluster and Dask client
# Adjust parameters as per your SLURM setup
cluster_kwargs = {
    "queue": "compute", 
    "cores": 8, 
    "memory": "16GB", 
    "walltime": "01:00:00",
    "local_directory": "/tmp/dask-worker-space" # Worker scratch space
}
# Scale to 10 SLURM jobs, each being a Dask worker
dask_cluster, dask_client = create_slurm_cluster(**cluster_kwargs, n_workers=10)

try:
    # Run workflow using the Dask client connected to the SLURM cluster
    results_dict = workflow.run_dask(client=dask_client)
    # Process results
finally:
    dask_client.close()
    dask_cluster.close()
```

### 4. Adaptive Basis Set Escalation

Automatically find a suitable basis set by converging energy components.

```python
from saptase.workflows.adaptive import AdaptiveWorkflow, run_adaptive_workflow
# Define monomer_a, monomer_b

# Define adaptive parameters
adaptive_opts = {
    "target_accuracy": { # kcal/mol
        "electrostatics": 0.1,
        "exchange": 0.1,
        "induction": 0.05,
        "dispersion": 0.05,
        "total": 0.1 # SAPT Total Energy
    },
    "max_rung": 3, # Max index in the default basis ladder
    # "basis_ladder": ["custom-basis1", "custom-basis2"] # Optionally provide a custom ladder
}

# Option 1: Using the convenience function
# Initial task uses the first basis in the ladder or a specified one.
initial_task = SaptTask(monomer_a, monomer_b, basis_set="jun-cc-pVDZ", method="sapt0") 
final_result, all_results_by_rung = run_adaptive_workflow(initial_task, adaptive_opts=adaptive_opts)

if final_result and final_result.success:
    print(f"Converged on basis: {final_result.basis_set} ({final_result.task_id})")
    print(f"Energy: {final_result.total_energy_kcal_mol():.4f} kcal/mol")

# Option 2: Using AdaptiveWorkflow directly
# adaptive_workflow = AdaptiveWorkflow(initial_task, adaptive_opts=adaptive_opts)
# final_result, all_results_by_rung = adaptive_workflow.run_adaptive()
# Process results...
```

### 5. Error Recovery & Provenance

SAPTASE automatically attempts to recover from common Psi4 errors (like SCF convergence failures) using a predefined strategy ladder. All attempts and outcomes are logged to an SQLite database (default: `runs/saptase_provenance.sqlite`) for detailed auditing. This is largely transparent to the user for the Psi4 backend.

### 6. Pauling-Point Sweeps (S22 Benchmark Example)

SAPTASE can generate and execute large sets of calculations for benchmarking.
The `scripts/build_sweep_yaml.py` script can generate a `sweep.yml` file for all dimers in a dataset (e.g., S22 located in `data/s22_split`) across multiple basis sets.

```bash
# Example: Generate a sweep file for the S22 dataset with specific bases
python scripts/build_sweep_yaml.py \
    --split-xyz-dir data/s22_split \
    --basis-list "jun-cc-pVDZ,aug-cc-pVDZ,def2-SVPD" \
    --out s22_sweep.yml

# Then run the generated sweep file
saptase run s22_sweep.yml --mode dask --scheduler your-scheduler-address
```
This workflow is used in `.github/workflows/pauling-sweep.yml` for automated benchmarking.

## Testing

SAPTASE uses `pytest`.

```bash
# Run all tests (Psi4-specific tests will be skipped if Psi4 is not found)
pytest

# Run only tests that DO NOT require Psi4 (mock tests, core logic)
pytest -m "not psi4"

# Run only tests that DO require a real Psi4 installation
pytest -m "psi4"
```

## Architecture & Development

Key architectural decisions are documented in Architecture Decision Records (ADRs) in the `docs/adr` directory.
For a detailed history of development, see `docs/dev/cascade-progress-log.md`.

## License

This project is licensed under the BSD-3-Clause License. See the `LICENSE` file for details.

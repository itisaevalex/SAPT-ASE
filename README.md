# SAPTASE: Automated Multi-Fidelity SAPT(DFT) Workflows
![version](https://img.shields.io/badge/version-0.4.0-blue)

SAPTASE is a Python framework for automating Symmetry-Adapted Perturbation Theory (SAPT) calculations with a focus on:

- Adaptive basis set selection
- Error recovery strategies
- Multi-fidelity approach (DMA and ML surrogates)
- Integration with popular QC packages (Psi4, CamCASP, SAPT2020)

## What's new in 0.4.0?

- Distributed execution via *Dask* (`--mode dask`).
- Scratch isolation & WAL-backed provenance DB for multi-process safety.
- Optional SLURM cluster helper (`create_slurm_cluster`).

## Minimum Viable Prototype (MVP)

The current version is **0.4.0** and includes distributed execution.

## Installation

### Dependencies

- Python 3.8+
- NumPy
- Psi4 

### Development Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/saptase.git
cd saptase

# Create a conda environment
conda create -n saptase python=3.10 numpy pytest
conda activate saptase

# Install Psi4
conda install -c psi4 psi4

# Install SAPTASE in development mode
pip install -e .
```

## Quick Example

```python
from saptase.core.models import Molecule
from saptase.core.orchestrator import run_sapt

# Create water molecules
water_a = Molecule.from_xyz_string("""3
Water A
O        -1.551007    -0.114520     0.000000
H        -1.934259     0.762503     0.000000
H        -0.599677     0.040712     0.000000
""")

water_b = Molecule.from_xyz_string("""3
Water B
O         1.350625     0.111469     0.000000
H         1.680398    -0.373741    -0.758561
H         1.680398    -0.373741     0.758561
""")

# Run SAPT calculation
result = run_sapt(water_a, water_b, basis_set="jun-cc-pVDZ", method="sapt0")

# Print results
print(f"Total interaction energy: {result.total_energy:.8f} Hartree")
print(f"                          {result.total_energy_kcal_mol():.4f} kcal/mol")
```

## Quick-start: Distributed execution & scratch control

Run via a *local* Dask cluster using CLI – scratch directories land under `tmp/scratch` and are deleted when done:

```bash
export SAPTASE_SCRATCH_ROOT=/tmp/scratch
saptase run job.yml --mode dask --workers 4
```

Keep scratch for debugging:

```bash
saptase run job.yml --mode dask --workers 4 --keep-scratch
```

### Local Dask demo

Run a simple demonstration using a *local* Dask cluster created automatically by the CLI:

```bash
saptase run examples/dask_local_demo.yml --mode dask # Explicitly request dask
```

This spins up an in-process LocalCluster and runs two dummy dimers using the configuration in [`examples/dask_local_demo.yml`](./examples/dask_local_demo.yml). The `--mode dask` flag ensures Dask execution, and since no `--scheduler` is provided, a local cluster is used.

### Submitting to SLURM

First install the *dask_jobqueue* extra:

```bash
pip install "saptase[dask_jobqueue]"
```

Then in Python:

```python
from saptase.execution.slurm import create_slurm_cluster
from saptase.execution.dask import DaskExecutor
from saptase.core.orchestrator import SaptWorkflow

cluster, client = create_slurm_cluster(queue="compute", cores=4, memory="8GB", n_workers=10)
workflow = SaptWorkflow()
# add tasks ...
workflow.run_dask(client=client)
```

## Testing

Run the test suite with:

```bash
pytest
```

If Psi4 is not available, tests requiring it will be skipped. You can still run the unit tests that don't require Psi4.

## License

This project is licensed under the BSD-3-Clause License.

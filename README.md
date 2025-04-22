# SAPTASE: Automated Multi-Fidelity SAPT(DFT) Workflows

SAPTASE is a Python framework for automating Symmetry-Adapted Perturbation Theory (SAPT) calculations with a focus on:

- Adaptive basis set selection
- Error recovery strategies
- Multi-fidelity approach (DMA and ML surrogates)
- Integration with popular QC packages (Psi4, CamCASP, SAPT2020)

## Minimum Viable Prototype (MVP)

The current version (0.1.0-mvp) implements the core functionality for running SAPT0 calculations with Psi4:

- Basic molecule representation with XYZ format support
- SAPT task and result data structures
- Psi4 backend for single-threaded SAPT0 calculations
- Simple workflow for running multiple SAPT tasks

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

## Testing

Run the test suite with:

```bash
pytest
```

If Psi4 is not available, tests requiring it will be skipped. You can still run the unit tests that don't require Psi4.

## License

This project is licensed under the BSD-3-Clause License.

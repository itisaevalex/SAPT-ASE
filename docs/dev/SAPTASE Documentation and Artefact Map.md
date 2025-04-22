# SAPTASE Documentation & Artefact Map

This map lists every persistent document, its purpose, authoring responsibility, file path, and update trigger.  Use it to keep the project repository organised and reproducible.

---
## 1  Repository‑Root Documents
| Path | Purpose | Maintainer | Update Trigger |
|------|---------|-----------|-----------------|
| `README.md` | Quick‑start, installation, minimal example | Core devs | Each new feature release |
| `CONTRIBUTING.md` | PR process, code style, CLA/DCO steps | Lead maintainer | Process changes |
| `CODE_OF_CONDUCT.md` | Community guidelines | Project owner | Rare |
| `LICENSE` | Academic‑permissive (BSD‑3‑Clause) | Project owner | On license change |
| `CHANGELOG.md` | Version history | Release captain | Every release tag |

---
## 2  Developer Docs (`/docs/dev/`)
| Document | Format | Source | Purpose |
|----------|--------|--------|---------|
| `architecture_blueprint.md` | Markdown | Based on Architectural Blueprint (Arch‑Analysis 1) | High‑level system overview |
| `adr/ADR‑xxxx.md` | Markdown | Created at each significant design decision | Record architectural decisions |
| `testing_strategy.md` | Markdown | From Dev Guide Section 3 | Explain unit/integration/regression tiers |
| `ci_pipeline.rst` | ReST | Dev Guide Section 4 | Pipeline description & badges |
| `error_taxonomy.md` | Markdown | SCF‑Analysis 1 | Enumerate error classes & recovery |
| `basis_selection_guide.md` | Markdown | Basis‑Analysis 1 | Detail ladder + tolerances |
| `ml_integration_guide.md` | Markdown | ML‑Analysis 2 | AP‑Net usage & UQ thresholds |

---
## 3  User Docs (`/docs/user/` – built by **JupyterBook**)
| Section | Content Source | When Updated |
|---------|----------------|--------------|
| **Installation** | Conda & pip instructions | Every release |
| **Quick Start Notebook** | `examples/quickstart.ipynb` | When API changes |
| **CLI Tutorial** | `examples/cli_demo.md` | When CLI flags change |
| **Adaptive Basis Tutorial** | Walk‑through with water dimer | When logic updates |
| **Distributed Execution** | Dask/SLURM workflow guide | On infra changes |
| **FAQ** | Curated from GitHub issues | Ongoing |

---
## 4  API Reference (`/docs/api/`)
* Auto‑generated via **Sphinx‑Autodoc** from inline docstrings.
* Re‑built on every CI doc job.

---
## 5  Benchmark & Validation (`/benchmarks/`)
| Folder | Contents | Maintainer |
|--------|----------|------------|
| `S22/` | Input XYZ, reference energies, result CSVs | Bench‑lead |
| `S66/` | … | … |
| `water_scan/` | Distance scan scripts & plots | … |
| `reports/2025‑Q2/` | HTML/MD performance report (wall‑time, memory) | Bench‑lead |

---
## 6  Provenance & State (`/runs/`) *git‑ignored*
* One subfolder per workflow run (timestamped).
  * `inputs/`, `outputs/`, `logs/`, `state.json`.
* SQLite DB `runs.sqlite` summarises key metadata for quick queries.

---
## 7  Release Artefacts
| Artefact | Location | Contents |
|----------|----------|----------|
| Source tarball | GitHub Releases | Tag snapshot |
| Wheel | PyPI | Built by CI on tag |
| Conda package | `conda-forge` feedstock | Binary + deps |
| Docker image | GHCR `ghcr.io/<org>/saptase` | Conda env + entrypoints |

---
## 8  External References
| Topic | Analysis Document | Citation |
|-------|------------------|----------|
| SCF recovery ladder | SCF‑Analysis 1 | Thesis Section 3.3 |
| Basis set ladder | Basis‑Analysis 1 | Section 3.2 |
| ML surrogate | ML‑Analysis 2 | Section 3.5 |
| Architecture rationale | Arch‑Analysis 2 | Section 2 |

---
## 9  Document Ownership Matrix
* **Core devs:** `README`, `architecture_blueprint`, API docs.
* **Release captain:** `CHANGELOG`, PyPI packaging.
* **Bench‑lead:** Benchmarks, performance reports.
* **QA lead:** Testing docs, CI config.

---
_End of Documentation & Artefact Map_


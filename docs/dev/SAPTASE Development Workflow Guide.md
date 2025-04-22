# SAPTASE Development Workflow Guide

## Purpose
This guide defines the engineering workflow for building **saptase**, covering coding standards, testing, documentation, CI, and release practice.  Follow it from the first prototype through publication.

---
## 1  Early Prototype (MVP) Milestone
* **Scope** – single‐job workflow running SAPT0/jun‑cc‑pVDZ via `Psi4Backend`, serial execution, YAML config loader.
* **Goal** – verify end‑to‑end data flow: `SaptTask → Psi4 → SaptResult`.
* **Deadline** – two weeks after project start.
* **Deliverables** – working CLI demo, minimal README, passing unit tests.

---
## 2  Phase Gate Checklist (applies to every development phase)
| Step | Description | Required Artefact |
|------|-------------|-------------------|
| 1 | **Design doc** – one‑pager in `/docs/dev/adr/` (architecture decision record). | Markdown file |
| 2 | **Implementation** – feature branch with type‑hinted code. | PR with linked issue |
| 3 | **Unit tests** – pytest coverage ≥ 90 % for new code. | `/tests/` files |
| 4 | **Docs** – docstrings + tutorial snippet in JupyterBook. | Sphinx build passes |
| 5 | **CI pass** – GitHub Actions workflow green (lint, mypy, tests). | CI badge |
| 6 | **Code review** – require at least one approval. | PR comment |
| 7 | **Merge & tag** – squash merge, semantic tag (e.g. `v0.3.0`). | Git tag |

---
## 3  Testing Strategy
### 3.1 Unit Tests
* Test pure functions in isolation.
* Mock Psi4/CamCASP subprocesses with `pytest‑monkeypatch`.

### 3.2 Integration Tests
* Spin‑up local Dask cluster (3 workers) within test; submit two dummy tasks.
* Verify provenance DB records and result aggregation.

### 3.3 Regression Benchmarks
* Store known energies for (H₂O)₂ and (NH₃)₂ in `/tests/data/`.  Fail build if deviation > 1e‑6 Ha.

---
## 4  Continuous Integration
### 4.1 Pipeline Stages (GitHub Actions)
1. **Lint** – `ruff`, `black --check`, `isort`.
2. **Type‑check** – `mypy`.
3. **Test** – `pytest -n auto` (no Psi4 for pure units, container with Psi4 for integration).
4. **Docs** – build Sphinx/JupyterBook; fail on warning.
5. **Publish** – (optional) build wheel + Docker image on tags starting with `v`.

### 4.2 Caching
* Cache Psi4 conda env to cut setup time.

---
## 5  Incremental Documentation Rules
* Each PR updates at least one of: API reference, example notebook, design doc.
* Use Google‑style docstrings; Sphinx `napoleon` renders them.
* Keep **changelog** in `CHANGELOG.md` (Keep‑a‑Changelog format).

---
## 6  User‑Experience Enhancements
* **Progress bars** via `tqdm` in CLI; updates every completed task.
* **Structured errors** – raise `SaptError(code, message, hint)`; CLI prints hint.
* **Result table** – `tabulate` summary on completion; optional CSV export.

---
## 7  Resource Estimation Helper
* Before run, estimate memory = `8 × N_basis²` bytes per monomer; warn if > 80 % of system RAM.
* Estimate wall‑time using linear model fitted from previous runs, stored in `~/.saptase/stats.db`.

---
## 8  Branch & Release Policy
* Default branch: `main` (protected).
* Feature branches: `feat/…`, `fix/…`.
* Semantic versioning; bump minor for new functionality, patch for fixes.

---
## 9  Risk & Mitigation
| Risk | Mitigation |
|------|-----------|
| AP‑Net dependency breaks | Pin commit hash; vendor small fork if critical |
| Dask cluster auth issues | Provide fallback local‑MPI executor |
| Psi4 API change | Continuous integration test matrix on latest + pinned versions |

---
## 10  Contribution Guide Snapshot
* Run `make precommit` before pushing.
* Sign off commits (`‑s`) for DCO compliance.

---
_End of Development Workflow Guide_


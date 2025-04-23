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
* **Local Parallelism:** Implement `run_local_parallel` using `concurrent.futures.ProcessPoolExecutor`. Ensure tests cover:
    - Correct distribution of tasks (e.g., two water dimers).
    - Aggregation of results from multiple processes.
    - Wall time reduction compared to serial execution.
    - Proper handling of `OMP_NUM_THREADS=1` in worker processes.
    - Pickling of `SaptTask` objects.
* **Multiprocessing Caveats (for `run_local_parallel`)**:
    *   **Pickling:** Objects passed between the main process and workers (like `SaptTask`, `SaptResult`, and potentially backend instances) must be pickleable. Dataclasses are generally fine, but avoid closures, generators, or complex non-serializable state.
    *   **Windows Compatibility:** Process creation on Windows requires extra care. The main script invoking parallel execution *must* be guarded by `if __name__ == '__main__':`. Task execution functions called by workers typically need to be defined at the top level of a module.
    *   **Thread Control (`OMP_NUM_THREADS`):** When worker processes call external programs (like Psi4) that might themselves be multithreaded, it's crucial to limit their thread count within the worker. Set `os.environ["OMP_NUM_THREADS"] = "1"` in the worker function (`_execute_task_for_parallel`) to prevent each worker from trying to use all available cores, leading to oversubscription and poor performance.
    *   **State Mutation:** Workers operate on *copies* of input objects. Changes made to these copies (e.g., updating `task.status`) are not automatically reflected in the original objects in the main process. The main process needs to explicitly update its state based on the results returned by the workers.

### 3.3 Regression Benchmarks
* Store known energies for (H₂O)₂ and (NH₃)₂ in `/tests/data/`.  Fail build if deviation > 1e‑6 Ha.

### 3.4 Adaptive Basis Set Workflow
*   **Logic:** The `AdaptiveWorkflow` (in `saptase.workflows.adaptive`) implements basis set escalation. It starts with a basis set (either specified by the user or the default first rung) and runs SAPT calculations iteratively up the `BASIS_LADDER` (defined in `saptase.core.basis`).
*   **Convergence:** After each rung (except the first), it compares the absolute difference in SAPT energy components between the current and previous rung against user-defined tolerances specified in the `target_accuracy` map in the job configuration.
*   **Stopping:** The workflow stops when all specified tolerances are met, or when the `max_rung` limit is reached. The final `SaptResult` indicates the basis set level at which convergence was achieved (or the max rung reached).
*   **Example Configuration:** See `docs/examples/job_adaptive.yml` for an example of how to configure an adaptive workflow job, including setting `target_accuracy` and `max_rung`.

---
## 4  Continuous Integration
### 4.1 Pipeline Stages (GitHub Actions)
1. **Lint** – `ruff`, `black --check`, `isort`. Ruff is configured with line-length 200 and ignores E501, N818, RUF003, PT006 to minimise friction for single-contributor development.
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

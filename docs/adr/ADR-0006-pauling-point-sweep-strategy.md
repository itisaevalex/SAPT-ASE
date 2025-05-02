# ADR-0006  Pauling-Point Sweep Implementation Strategy

**Date:** 2025-05-02
**Status:** Accepted

## 1  Context

To evaluate "Pauling-point" convergence behaviour we need SAPT0 interaction energies for every *dimer × basis* pair in the S22 benchmark:

* 22 dimers
* 12 basis sets (jun/aug/jul-cc-pV\[D,T,Q]Z and def2-\[SVPD,TZVPD,QZVPD,TZVPPD])
* **264 single-point jobs**

Key constraints:

| Requirement             | Motivation                                           |
| ----------------------- | ---------------------------------------------------- |
| **Robustness**          | nightly CI must always finish; no manual babysitting |
| **Cost predictability** | stay < $60 on GitHub large runners                  |
| **Reproducibility**     | all inputs + provenance DB + scratch archived        |
| **Clarity**             | Psi4 must receive *distinct* monomer A/B blocks      |

Early spikes exposed three issues:

1. Psi4 chokes when the dimer XYZ is passed verbatim (overlapping atoms).
2. `saptase` leaked `scratch_root` / `keep_scratch` into `psi4.set_options()`.
3. Off-by-one in `Molecule.from_xyz_string` surfaced when final newlines were missing.

## 2  Decision

We adopt the following design.

| #      | Decision element                                                                                                                                                                                                    |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **D1** | **Pre-split monomer geometry files.** Each dimer is stored as `idx_name_a.xyz` + `idx_name_b.xyz` under `data/s22_split/` (checked into Git).                                                                       |
| **D2** | **Input sanitiser.** `scripts/fix_xyz.py` enforces: (i) exactly one comment line, (ii) trailing `\n`. This eliminates the Molecule parser bug without patching the vendor code.                                     |
| **D3** | **Sweep spec generator.** `scripts/build_sweep_yaml.py --split-xyz-dir data/s22_split` enumerates (dimer, basis) and emits `sweep.yml` with *relative* paths.                                                       |
| **D4** | **Full-grid execution (no adaptive ladder).** We run all 264 points; the Pauling point is derived later from the SQLite log.                                                                                        |
| **D5** | **GitHub Actions workflow (`pauling-sweep.yml`).** One 16-core large runner, `local_parallel` mode, `$SAPTASE_SCRATCH_ROOT=/mnt/ramdisk`, WAL-mode SQLite, artifacts upload (`runs/`, `sweep.yml`, tarred scratch). |
| **D6** | **Psi4 scratch context wrapper** inside `Psi4Backend._calculate_inner`, plus hot-fix that strips illegal keys before `psi4.set_options()`.                                                                          |
| **D7** | **Checkpoint/resume.** The provenance DB is uploaded every run; reruns detect completed tasks and skip them.                                                                                                        |

## 3  Consequences

### 3.1  Positive

* **Deterministic coverage** – every basis is available for Pauling-point plots.
* **Zero ambiguity** – split files guarantee Psi4 gets correct monomers.
* **Portable paths** – relative references work identically on local dev boxes and CI runners.
* **Scratch isolation** – each task uses its own sub-dir on the runner's NVMe tmpfs, deleted after tar.
* **Fail-safe parsing** – newline sanitiser removes the last outstanding source of "expected N, found N-1".

### 3.2  Negative / Trade-offs

* Slight repository bloat (≈40 kB for 44 monomer XYZ files).
* Full grid is ~2 h on a 16-core runner; adaptive ladder would be faster but is less transparent.
* Backend hot-fix masks the deeper config-validation problem – must be revisited upstream.

## 4  Implementation Notes

* **Cost model**: 16-core large runner @ $0.432 min-¹ × 120 min ≈ $52.
* **Fail-fast**: `timeout-minutes: 180` on the GHA job avoids runaway spend.
* **Concurrency**: `--max-workers $(nproc)`; WAL busy timeout 10 s prevents "database is locked".
* **Artifacts**: `saptase-pauling-results` (≈150 MB compressed) retained 14 days.
* **Local smoke test**:

  ```bash
  python scripts/fix_xyz.py
  python scripts/build_sweep_yaml.py --split-xyz-dir data/s22_split --out test.yml --basis-list jun-cc-pVDZ
  saptase run test.yml --mode local_parallel --max-workers 1
  ```

## 5  Alternatives Considered

| Option                                      | Why rejected                                                               |
| ------------------------------------------- | -------------------------------------------------------------------------- |
| **Inline XYZ strings** generated on the fly | more complex generator; harder to debug than plain files                   |
| **Auto-splitting inside `saptase`**         | prototype failed (`atoms are too close`); invasive change to task schema   |
| **Patch `Molecule.from_xyz_string`**        | would require vendoring the library; sanitiser is simpler and future-proof |
| **Adaptive ladder only**                    | hides outliers; reviewers asked for the *entire* convergence surface       |

## 6  Future Work

* Upstream PR to `saptase` fixing the off-by-one and option-leak issues (remove need for D2 & D6).
* Add second workflow that **derives** the Pauling point per dimer from the 264-point DB and commits a markdown report + PNG plot to `gh-pages`.
* Explore caching of integral files to trim runtime on reruns.

---

**Lead author:** *Alex Isaev*
*Reviewed by*: team-chem-compute, advisory board 
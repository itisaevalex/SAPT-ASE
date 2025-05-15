# ADR-0008: ML‑Accelerated Interaction Energies

**Date:** 2025‑05‑14
**Status:** Proposed
**Authors:** Alex Isaev (@a‑isaev), Gizmo AI assistant, ML working group
**Reviewed by:** team‑chem‑compute, infrastructure, advisory‑board

---

## 1 Context

ADR‑0006 established a deterministic "Pauling‑point" sweep (SAPT0 on a 12‑basis ladder) as the reference method for non‑covalent interaction energies.  While robust, the 264‑job grid costs ≈2 h on a 16‑core runner and scales linearly with the number of dimers.  Recent progress in molecular graph neural‑net (GNN) surrogates shows sub‑0.2 kcal mol⁻¹ RMSE for SAPT components at milli‑second evaluation cost.

The project now targets:

* **Faster iteration** during dataset curation and method development.
* **Cheaper CI/nightly runs** without sacrificing accuracy or auditability.
* **A foundation for active‑learning and error‑prediction extensions.**

---

## 2 Problem Statement

We need a surrogate model that can predict SAPT(DFT, CBS) interaction energies for arbitrary dimers **within 0.25 kcal mol⁻¹** while reducing wall‑time and CPU‑hours by ≥ 20× compared with the Pauling‑point sweep.

---

## 3 Decision Drivers

| Driver                | Motivation                                                                                                               |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| **Accuracy parity**   | Must match or improve on Pauling‑point (SAPT0/Pauling) error envelope on S22 and expanded benchmarks.                    |
| **Reproducibility**   | Training recipe, random seeds, model artefacts + hashes stored in provenance DB.                                         |
| **Maintainability**   | Use mainstream PyTorch 2 / Lightning; avoid niche libs.                                                                  |
| **Resource fit**      | Must train overnight on developer‑grade hardware (e.g. Ryzen 9 5900HX + RTX 3070 8 GB) and run inference on CPU‑only CI. |
| **Graceful fallback** | When model hash missing or topology unsupported, pipeline reverts to the Pauling‑point grid.                             |

---

## 4 Scope

**In‑scope (Phase 1):**

1. Δ‑learning surrogate (`E_target` = SAPT(DFT,QZ) – SAPT0(DZ)).
2. Models: SchNet & PaiNN baselines, CLIFF descriptor + KRR fallback.
3. Data: 100 k randomly sampled dimers from Splinter‑Dataset (≤64 atoms) with SAPT0(DZ); 5 k high‑level SAPT(DFT,QZ) subset for labels.
4. Integration hooks in `saptase` CLI + backend.
5. CI workflow for weekly training & performance gating.

**Out‑of‑scope:** equivariant l > 1 models, long‑range transformer surrogates, NequIP, geometry optimisation loops.

---

## 5 Detailed Proposal

### 5.1 Model architecture

| Variant          | Layers               | Hidden dim | Params | GPU mem (batch = 64) |
| ---------------- | -------------------- | ---------- | ------ | -------------------- |
| **SchNet‑Small** | 4 interaction blocks | 128        | 1.0 M  | 7.1 GB               |
| **PaiNN‑Medium** | 3 message blocks     | 128        | 1.2 M  | 7.5 GB               |
| **CLIFF‑FCHL**   | kernel               |  –         | <0.1 M | CPU‑only             |

* Mixed‑precision (AMP) and Torch 2 compile for throughput.
* Early stopping on validation MAE.
* Ensemble of 3 for uncertainty; stored as separate `.pt` files.

### 5.2 Training pipeline (PyTorch Lightning)

```yaml
trainer:
  accelerator: gpu
  devices: 1
  precision: 16-mixed
  max_epochs: 120
  callbacks:
    - EarlyStopping(patience=20, monitor=val_mae)
    - ModelCheckpoint(monitor=val_mae, save_top_k=1)
```

Dataset loader uses `torch_geometric` `DataLoader` with `num_workers=8` and host‑pinned memory.

### 5.3 Task orchestration (new CLI)

```bash
# train & log metrics
time saptase train ml --config confs/schnet.yml --out models/schnet_sapt0.pt

# predict in place of Psi4
time saptase run sweep.yml --mode local_parallel \
       --max-workers 8 \
       --ml-surrogate models/schnet_sapt0.pt
```

`Backend._calculate_inner` checks `task.method == "ml_surrogate"` and switches to the model path via `torch.jit.load()`.

### 5.4 CI/CD workflow (`.github/workflows/ml.yml`)

* Weekly schedule.
* Large GHA runner w/ GPU (ubuntu‑latest + cuda‑12).
* Steps:

  1. Cache / download raw Splinter shards.
  2. Execute `saptase train ml ...`.
  3. Run hold‑out S22 + HBC6 tests; fail if val MAE > 0.3.
  4. Attach model artefact to release & push hash to repo via PR.

### 5.5 Provenance DB schema changes

```sql
CREATE TABLE ml_models (
  hash TEXT PRIMARY KEY,
  path TEXT,
  architecture TEXT,
  train_data_tag TEXT,
  saptase_commit_sha TEXT,
  date TEXT,
  metrics JSON
);
```

`results` table gains column `ml_hash` (nullable).

---

## 6 Best Practices

* **Seed control:** set `torch.manual_seed(42)` in both training and inference.
* **Version pinning:** lock Torch, CUDA, PyG, Lightning in `pyproject.toml`.
* **Reversible preprocessing:** store SMILES + XYZ + charge/ multiplicity for every training sample.
* **Unit conversion:** energies in kcal mol⁻¹ to avoid floating‑point drift.
* **Schema invariance:** assert identical ordering of atoms across monomer A/B when featurising.
* **Fallback policy:** if `ml-surrogate` fails (missing GPU, unsupported atom types), raise `MLSurrogateError` → caught by scheduler → job resubmitted as Pauling‑point.
* **Security:** verify SHA‑256 of model file against DB before `torch.load()`.

---

## 7 Testing & Validation

| Layer           | Test                            | Threshold                     |
| --------------- | ------------------------------- | ----------------------------- |
| **Unit**        | featuriser → tensor dims        | exact match                   |
| **Integration** | 264‑point sweep on S22 with ML  | runtime ≤15 min, mean ΔE ≤0.3 |
| **Regression**  | weekly CI val MAE drift         | σₙ2ₗ < 1.2× historical        |
| **Robustness**  | 500 random perturbed geometries | no runtime crash              |

---

## 8 Risks & Mitigations

| Risk                                      | Impact                       | Mitigation                                                           |
| ----------------------------------------- | ---------------------------- | -------------------------------------------------------------------- |
| Poor extrapolation outside training space | Wrong energies in production | Ensemble uncertainty → fallback to Pauling‑point                     |
| CUDA / driver mismatch on dev machines    | Blocking adoption            | Provide CPU‑only CLIFF fallback, conda env file with cudatoolkit pin |
| CI GPU quota exhaustion                   | Delayed model updates        | Switch to self‑hosted runner or scale down training frequency        |

---

## 9 Timeline

| Week | Milestone                                                 |
| ---- | --------------------------------------------------------- |
|  W20 | Dataset curation script, initial SchNet baseline (local)  |
|  W21 | CLI integration & backend bypass, provenance schema patch |
|  W22 | CI workflow live, validation gating on S22                |
|  W23 | PaiNN + ensemble uncertainty, ADR status → *Accepted*     |

---

## 10 Future Work

* **E2 Active‑learning ladder** – use uncertainty to pick new basis / dimer points.
* **E3 CBS ML extrapolation** – surrogate over (basis‑ζ, E) → CBS.
* **E4 Error predictor** – classify SCF failure likelihood.
* **E5 Full ML‑only mode** – combine Δ‑learning + CBS surrogate, ship TorchScript.

---

## 11 References

1. Schütt, K. T. *et al.* "SchNet – A deep learning architecture for molecules and materials" (2018).
2. Gillis, A. "AP‑Net: Interaction energy decomposition with neural nets" (*J. Chem. Phys.*, 2023).
3. Christensen, A. S. *et al.* "FCHL and CLIFF kernels for molecular properties" (2020).

---

*End of document*

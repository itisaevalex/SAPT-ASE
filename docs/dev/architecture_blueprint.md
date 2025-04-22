# Automated Multi‑Fidelity SAPT(DFT) 
Adaptive Basis Selection • Error Recovery • Multipoles & ML Surrogates


## 1  Aims and Audience

- **Aim** – Deliver a Python framework that
    
    - drives **Psi4** SAPT(DFT) jobs,
        
    - picks the cheapest basis set that meets user‑defined tolerances,
        
    - rescues failed runs via a keyword‑ladder,
        
    - swaps to fast surrogates (DMA or ML) when accuracy allows,
        
    - optionally cross‑checks with **CamCASP** and **SAPT2020**.
        
    - 👷 **Early prototype (MVP)** after Phase 2  → see Dev Guide §1.
        
- **Audience** – Computational chemists, force‑field builders, method developers.
    

---

## 2  Background

- SAPT theory and DFT‑based variants.
    
- Psi4, SAPT2020, CamCASP: scope, licences, Python friendliness.
    
- Basis convergence; calendar sets (jun/jul‑cc‑pVXZ), def2‑TZVPPD.
    
- Typical failure modes; recovery tactics.
    
- Distributed multipole analysis (GDMA, HORTON, ISA).
    
- ML for SAPT components – AP‑Net, Splinter, SAPT‑PDB‑13K.
    
- Benchmarks – water dimer, ammonia dimer, S22, S66, SAPT‑10K, Splinter.
    

---

## 3  Methods and Implementation

### 3.1 Workflow Architecture

`geometry → energy_estimate → error_handling → log → next_case`

- ASE builds and samples dimers.
    
- Back‑end abstraction: `"psi4"` (efault) | `"camcasp"` | `"sapt2020"`.
    
- Fragment separation enforced at I/O layer.
    

### 3.2 Adaptive Basis Selection

- YAML table maps system size + target error to basis ladder.
    
- Per‑component tolerances (e.g. `|ΔE_disp| < 0.2 kcal mol⁻¹`, `|ΔE_tot| < 0.5`).
    
- Escalate: **jun‑DZ → aug‑DZ → jun‑TZ → aug‑TZ**.
    

### 3.3 Error Recovery

Escalation ladder

1. restart SCF with DF guess, extra iterations, damping off, level shift 0.5 Eh
    
2. add DIIS reset every five cycles
    
3. switch **ROHF** then back‑project to RHF **or invoke SOSCF** if UHF fails
    
4. shrink basis one rung
    
5. mark _unrecoverable_ after _N_ retries (default = 3). Resource guard monitors RAM, disk, wall time; kills runaway processes.
    

### 3.4 Distributed Multipole Analysis

- HORTON (ISA) grabs multipoles (`ℓ ≤ 4`) from Psi4 wavefunctions.
    
- Coulomb tensor sums give electrostatic term; optional charge‑transfer via virtual charge flow.
    
- Mode `dma_only` skips SAPT for quick screening.
    

### 3.5 Machine Learning Module

- Ensemble‑dropout **AP‑Net** (equivariant GNN) predicts SAPT0 components.
    
- Reject prediction when `σ > 0.3 kcal mol⁻¹`.
    
- Active‑learning loop: add high‑σ cases to training cache, retrain nightly.
    

---

## 4  Technical Enhancements

- **Config** – hierarchical YAML profiles (`default`, `scan`, `refine`).
    
- **CLI** – `python -m saptase run job.yml --override basis.max_iter=150`.
    
- **Logging** – SQLite; schema versioned; auto‑vacuum on close.
    
- **Parallelism** – Local execution via `SaptWorkflow.run_local_parallel` uses `concurrent.futures.ProcessPoolExecutor` for multi-core parallelism on a single machine (typically ≤ 8 jobs). Distributed execution across clusters leverages Dask.
    
- **CI** – GitHub Actions executes linting, type‑checking & pytest on every push.
    
- **Packaging** – `pyproject.toml`, Conda, Docker (Psi4 + CamCASP pre‑built).
    
- **Docs** – JupyterBook; tutorials, API, developer guide.
    
- **UX** – structured error messages and `tqdm` progress bars.
    

---

## 5  Library Layout

```text
saptase/
├─ core/
│   ├─ orchestrator.py   # run_sapt / run_dma / run_ml
│   ├─ basis.py          # calendar logic, aux‑fit map
│   └─ backend.py        # CamCASP & SAPT2020 wrappers
├─ workflows/
│   ├─ adaptive.py       # basis ladder
│   ├─ screen.py         # ML/DMA pre‑filter
│   └─ devset.py         # active learning
├─ recovery/
│   ├─ scf.py            # low‑level tricks
│   ├─ escalate.py       # ladder control
│   └─ monitor.py        # RAM/disk/wall checks
├─ io/
│   ├─ geom.py           # ASE ↔︎ Psi4
│   ├─ multipole.py      # HORTON/GDMA
│   └─ camcasp_io.py
├─ ml/
│   ├─ apnet.py
│   └─ uncertainty.py
├─ cli.py
└─ tests/
    ├─ data/
    └─ test_end2end.py
```

---

## 6  Benchmarking and Validation

- Datasets: water, ammonia, S22, S66, SAPT‑PDB‑13K subset.
    
- Metrics: accuracy vs. literature, wall time per system, failure count, recovery success.
    
- Cross‑check Psi4 vs. CamCASP first‑order terms on ten S22 dimers; accept `|ΔE_elst| < 0.05 kcal mol⁻¹`.
    

---

## 7  Discussion Points

- Cost‑accuracy “Pauling points”.
    
- When DMA or ML is “good enough”.
    
- Limits: closed‑shell only, two‑body only.
    
- Future: open‑shell, three‑body, Psi4‑CUDA, XSAPT extrapolation.
    
- **User‑experience focus** – clarity of errors and visual summaries.
    

---

## 8  Appendices

- Full YAML schema.
    
- CLI usage cheat‑sheet.
    
- Sample Jupyter notebook.
    
- Raw benchmark tables (CSV).
    

### Key tool references

- Psi4 manual [https://psicode.org/psi4manual/master/sapt.html](https://psicode.org/psi4manual/master/sapt.html)
    
- CamCASP [https://www-stone.ch.cam.ac.uk/programs.html](https://www-stone.ch.cam.ac.uk/programs.html)
    
- SAPT2020 [https://github.com/kcsaller/SAPT2020](https://github.com/kcsaller/SAPT2020)
    
- HORTON [https://horton.readthedocs.io](https://horton.readthedocs.io)
    
- AP‑Net paper [https://doi.org/10.1039/D4SC00000A](https://doi.org/10.1039/D4SC00000A)
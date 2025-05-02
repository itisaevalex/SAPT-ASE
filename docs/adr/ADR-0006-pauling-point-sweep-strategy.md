# ADR-0006: Pauling-Point Sweep Implementation Strategy

**Date:** 2025-05-02
**Status:** Accepted

## Context

We need to implement a workflow to perform a SAPT0 "Pauling-point" benchmark across the S22 dataset and a defined list of 12 basis sets (jun/aug/jul-cc-pV[D,T,Q]Z and def2-[SVP,TZVP,QZVP,TZVPP]D). This involves running 22 dimers × 12 basis sets = 264 individual SAPT0 calculations.

The primary goals are robustness, efficiency on GitHub Actions large runners, cost predictability, and complete artifact capture for reproducibility and analysis.

Initial investigations revealed issues with:
- Correctly defining monomer inputs for SAPT calculations (Psi4 backend requires separate monomer definitions).
- Handling Psi4 scratch directory configuration correctly from within `saptase`.
- Potential inconsistencies in how configuration options (like `scratch_root`, `keep_scratch`) were passed between `saptase` layers and the Psi4 backend.

## Decision

We will implement the Pauling-point sweep using the following strategy:

1.  **Full Grid Calculation:** The workflow will execute all 264 SAPT0 calculations explicitly. It will *not* use the adaptive basis set ladder approach for this specific benchmark, ensuring results are available for every basis set.
2.  **Pre-Split Monomer Files:** Input geometries will be provided as pre-split monomer files (`*_a.xyz`, `*_b.xyz`) located in a dedicated directory (`data/s22_split`). This directory will be checked into the repository for availability during GitHub Actions runs.
3.  **YAML Generation Script:** A script (`scripts/build_sweep_yaml.py`) will generate the `sweep.yml` job file. It will:
    - Accept the split monomer directory via `--split-xyz-dir`.
    - Iterate through `*_a.xyz` files, find corresponding `*_b.xyz` files.
    - Generate tasks for each dimer/basis pair.
    - Define `monomer_a.file` and `monomer_b.file` using **relative paths** from the repository root (e.g., `data/s22_split/...`) for portability between local and runner environments.
4.  **GitHub Actions Workflow (`pauling-sweep.yml`):**
    - Target a large runner (e.g., `ubuntu-latest-16-core` or similar, initially set to `ubuntu-latest` for testing).
    - Use `actions/checkout@v4` to retrieve the code and the committed `data/s22_split` directory.
    - Set up the conda environment using `mamba-org/setup-micromamba` and `environment-ci.yml`.
    - Verify the presence of `data/s22_split`.
    - Call `scripts/build_sweep_yaml.py --split-xyz-dir data/s22_split ...` to create `sweep.yml`.
    - Execute the sweep using `saptase run sweep.yml --mode local_parallel -w $(nproc)`.
    - Set appropriate environment variables for scratch (`SAPTASE_SCRATCH_ROOT=/mnt/ramdisk/saptase_scratch`), database (`DB_FILE=runs/pauling.sqlite`), and concurrency (`WAL_BUSY=10000`).
    - Compress and upload results (`runs/`, scratch directory, `sweep.yml`) as artifacts.
    - Implement checkpointing/resume by uploading/downloading the `pauling.sqlite` database (as suggested in the initial prompt example, although not explicitly re-added in the final workflow edits).
5.  **Psi4 Backend Scratch Handling (`saptase.core.backend.Psi4Backend`):**
    - Use a context manager (`_psi4_scratch`) within `_calculate_inner` to temporarily set both the `PSI_SCRATCH` environment variable and the `psi4.core.IOManager.shared_object().set_default_path()` based on the scratch directory provided by `TaskScratch`.
    - Ensure these settings are restored correctly upon exiting the context.
    - Explicitly remove `scratch_root` and `keep_scratch` from the `psi4_options` dictionary before calling `psi4.set_options()` as a hot-fix to prevent errors caused by these keys potentially leaking from `task.additional_keywords`.

## Consequences

- **Pros:**
    - Robust and explicit calculation of all required data points.
    - Clear separation of monomer inputs, avoiding ambiguity.
    - Correct and portable handling of file paths.
    - Correctly configures Psi4 scratch space via standard mechanisms (environment variable, IOManager API).
    - Avoids passing invalid options (`scratch_root`, `keep_scratch`) to Psi4.
    - Workflow aligns well with GitHub Actions best practices (runner selection, environment caching, artifact handling).
- **Cons:**
    - Does not dynamically determine the Pauling point; requires post-processing of all results.
    - Requires maintaining the pre-split monomer files.
    - The hot-fix for removing illegal keys in the backend masks the underlying issue of how `additional_keywords` are populated; this should be addressed later in the config loading logic.

## Alternatives Considered

- **Single Dimer File Input:** Attempted to configure `saptase` to automatically split a single dimer XYZ file provided for both monomers. This failed as Psi4 received duplicate atoms (`atoms are too close` error).
- **Inline Monomer XYZ:** Considered modifying `build_sweep_yaml.py` to parse dimer files and generate inline XYZ strings for monomers. Rejected in favor of the simpler pre-split file approach as the files were available.
- **Direct `set_local_scratch` Call:** Attempted calling `psi4.core.set_local_scratch`, which resulted in an `AttributeError`, indicating the function doesn't exist as named/called. 
param(
    [string]$Workers = "1",
    [string]$ExampleYaml = "./examples/dask_local_demo.yml"
)

# -----------------------------------------------------------------------------
# Windows-friendly helper script that reproduces the CI test
# `tests/test_cli_run.py::test_cli_run_local_dask_success`.
# It launches the SAPTASE CLI in a temporary working directory using a
# one-worker LocalCluster (Dask) backend, then prints the provenance rows
# recorded to the SQLite database.
# -----------------------------------------------------------------------------

# 1. Prepare isolated temp directory & scratch root
$TempDir   = Join-Path $env:TEMP ("saptase_cli_" + ([guid]::NewGuid().ToString()))
$Scratch   = Join-Path $TempDir "scratch"
New-Item -ItemType Directory -Path $TempDir   | Out-Null
New-Item -ItemType Directory -Path $Scratch   | Out-Null

# 2. Environment for fast/no-Psi4 execution
$env:CI_FAST         = "1"    # instructs fixtures to use lightweight mock backend
$env:OMP_NUM_THREADS = "1"

# 3. Run the CLI
Write-Host "[SAPTASE] Running CLI in $TempDir ..." -ForegroundColor Cyan
python -m saptase.cli --scratch-root "$Scratch" run "$ExampleYaml" `
       --mode dask --workers $Workers
if ($LASTEXITCODE -ne 0) {
    Write-Error "CLI exited with status $LASTEXITCODE"
    exit $LASTEXITCODE
}

# 4. Inspect the provenance DB
$DbPath = Join-Path $TempDir "runs/runs.sqlite"
if (Test-Path $DbPath) {
    Write-Host "[SAPTASE] Provenance database found at $DbPath" -ForegroundColor Green
    python -c "import sqlite3, json, sys; db=r'$DbPath'; conn=sqlite3.connect(db); rows=conn.execute('SELECT task_id, status FROM task_log').fetchall(); conn.close(); print(json.dumps(rows))"
} else {
    Write-Warning "Provenance DB not created – something went wrong"
}

Write-Host "[SAPTASE] Finished. Temporary run directory:`n  $TempDir" -ForegroundColor Cyan

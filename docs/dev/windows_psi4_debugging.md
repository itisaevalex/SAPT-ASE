# Windows Psi4 Debugging Guide

This document provides troubleshooting steps for common Psi4 installation and runtime issues on Windows, particularly those related to DLL loading problems.

## Common Issue: Missing MKL Runtime DLL

One of the most common issues on Windows is the Intel Math Kernel Library (MKL) DLL not being found by Psi4, which results in import errors like:

```
ImportError: DLL load failed while importing core: The specified procedure could not be found.
```

### Root Cause

Psi4's Windows wheel **must** load `mkl_rt.2.dll` (Intel MKL). If that DLL isn't visible in the PATH, `import psi4` aborts with the error "procedure could not be found."

The critical components are:
- `mkl_rt.2.dll` - Math Kernel Library runtime
- `libiomp5md.dll` - Intel OpenMP runtime

## Step-by-Step Resolution

Follow these steps to fix MKL-related issues in your Psi4 environment:

### 1. Diagnose the Problem

First, check if the system can find the necessary DLLs:

```python
import ctypes.util, platform, sys
print("mkl_rt  ->", ctypes.util.find_library("mkl_rt"))
print("iomp5   ->", ctypes.util.find_library("libiomp5md"))
```

If `mkl_rt` shows `None` but `iomp5` is found, you have the typical MKL visibility issue.

### 2. Install or Reinstall MKL Components

Ensure you're in your Psi4 conda environment (typically `psi4-py310` or similar), then run:

```powershell
conda install -c conda-forge --yes --force-reinstall mkl "libblas=*=*mkl"
```

This does two important things:
- `mkl` → Places **mkl_rt.2.dll** into `…\Library\bin\`
- `libblas=*=*mkl` → Ensures BLAS/LAPACK points at MKL, not OpenBLAS

### 3. Fix the PATH Environment

Even after installation, Windows may not find the MKL DLL because it's not in the PATH. You can temporarily fix this with:

```powershell
$env:PATH = "$env:CONDA_PREFIX\Library\bin;$env:PATH"
```

Then verify the DLLs are found:

```python
import ctypes.util
print("mkl_rt  ->", ctypes.util.find_library("mkl_rt"))
print("iomp5   ->", ctypes.util.find_library("libiomp5md"))
```

### 4. Try Importing Psi4

With MKL now in the PATH, test if Psi4 imports correctly:

```powershell
python -c "import psi4, sys; print('Psi4', psi4.__version__, 'imported on', sys.version.split()[0])"
```

You should see something like:
```
Psi4 1.9.1 imported on 3.10.17
```

### 5. Make the PATH Fix Permanent

To avoid repeating these steps each time, create a conda activation hook:

```powershell
$hook = "$env:CONDA_PREFIX\etc\conda\activate.d\add-library-bin.ps1"
New-Item -Force -ItemType Directory (Split-Path $hook) | Out-Null
' $env:PATH = "$env:CONDA_PREFIX\Library\bin;$env:PATH" ' | Set-Content $hook
```

This ensures that every time you activate your Psi4 environment, the necessary MKL libraries are automatically added to the PATH.

## Other Potential Issues

### Missing Psi4 Package

If you get `ModuleNotFoundError: No module named 'psi4'`, your Psi4 installation may be missing or corrupted. Fix it with:

```powershell
conda install -c psi4 psi4
```

### Environment Activation Issues

If conda environment activation isn't working properly:

1. Try explicitly using the activation script:
   ```powershell
   & C:\Users\username\anaconda3\Scripts\activate.ps1 psi4-py310
   ```

2. Verify you're in the right environment:
   ```powershell
   echo $env:CONDA_PREFIX
   ```

### Unicode Encoding Errors

Windows PowerShell may have issues with Unicode characters. If you see errors like:

```
UnicodeEncodeError: 'charmap' codec can't encode character '\u2713'
```

Avoid using Unicode characters (like checkmarks ✓) in your scripts and command outputs.

## Summary

Most Windows Psi4 issues stem from the MKL DLL not being found. The solution pattern is:

1. Install/reinstall MKL components
2. Ensure Library\bin is on the PATH
3. Create an activation hook for permanent fixes

If you still encounter issues after following these steps, please report them with your specific error messages and environment details.

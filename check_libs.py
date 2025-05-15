import ctypes.util, platform, sys
import os

print("mkl_rt  ->", ctypes.util.find_library("mkl_rt"))
print("iomp5   ->", ctypes.util.find_library("libiomp5md"))

# Check if the file exists directly
lib_bin_path = os.path.join(os.environ.get('CONDA_PREFIX', ''), 'Library', 'bin')
print("\nChecking directly for files:")
mkl_path = os.path.join(lib_bin_path, 'mkl_rt.2.dll')
print(f"mkl_rt.2.dll exists: {os.path.exists(mkl_path)}")
print(f"Full path: {mkl_path}")

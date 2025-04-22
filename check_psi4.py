import os
import sys
import traceback

print("--- Starting Psi4 Import Check ---")
print(f"Python Executable: {sys.executable}")
print(f"Current Working Directory: {os.getcwd()}")
print(f"Python Path: {sys.path}")

try:
    print("Attempting to import psi4...")
    import psi4

    print("Import successful!")
    print(f"Psi4 Version: {psi4.__version__}")
    print(f"Psi4 Path: {psi4.__file__}")
except ImportError as ie:
    print(f"Caught ImportError: {ie}")
    traceback.print_exc()
except Exception as e:
    print(f"Caught other Exception: {e}")
    traceback.print_exc()
except BaseException as be:
    # This might catch more severe errors like SystemExit
    # but often won't catch low-level C++ crashes (segfaults)
    print(f"Caught BaseException: {be}")
    traceback.print_exc()
finally:
    print("--- Finished Psi4 Import Check ---")

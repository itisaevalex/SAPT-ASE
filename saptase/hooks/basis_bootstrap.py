from __future__ import annotations

import logging

# import json # Not used in the patch
# import shutil # Not used in the patch
import os  # Still needed for CONDA_PREFIX fallback in one version of the logic
import sys
from pathlib import Path

import basis_set_exchange as bse
import psi4

logger = logging.getLogger(__name__)

# Global list of bases to check if ensure_bases is called without an argument
# This maintains previous behavior if ensure_bases() is called directly from elsewhere.
REQUESTED_DEFAULT = [
    "jul-cc-pVDZ",
    "jul-cc-pVTZ",
    "jul-cc-pVQZ",
    "jun-cc-pVDZ",
    "jun-cc-pVTZ",
    "jun-cc-pVQZ",
    "aug-cc-pVDZ",
    "aug-cc-pVTZ",
    "aug-cc-pVQZ",
    "def2-SVPD",
    "def2-TZVPD",
    "def2-QZVPD",
    "def2-TZVPPD",
]


def _download_and_write(name: str, target_dir: Path) -> bool:  # Added type hint for return
    """Grab basis `name` from BSE and write <canonical>.gbs into target_dir."""
    try:
        try:
            canonical = bse.lut.get_basis_aliases(name)[0]
        except AttributeError:  # BSE < 0.9 fallback
            logger.debug(
                f"[bootstrap] bse.lut.get_basis_aliases not found (BSE < 0.9?). Falling back to name.lower() for {name}"
            )
            canonical = name.lower()
        except Exception as e:  # Catch other potential errors during alias lookup
            logger.warning(
                f"[bootstrap] Error getting alias for {name}: {e!s}. Using name.lower()."
            )
            canonical = name.lower()

        gbs = bse.get_basis(
            canonical, fmt="psi4", header=False
        )  # Added header=False as in previous correct versions
        outfile = target_dir / f"{canonical}.gbs"
        outfile.write_text(gbs)
        logger.info(f"[bootstrap] Installed {canonical} (requested as {name}) → {outfile}")
        return True
    except Exception as e:
        logger.error(
            f"[bootstrap] Could not fetch/write {name} (canonical: {canonical if 'canonical' in locals() else 'unknown'}): {e!s}"
        )
        return False


def ensure_bases(requested: list[str] | None = None) -> None:  # Added type hint for return
    """Ensure every basis in `requested` exists in Psi4's .gbs directory."""
    if requested is None:
        requested = REQUESTED_DEFAULT

    # Robustly locate the directory
    basis_dir = None
    try:
        psi4_datadir = psi4.core.get_global_option("PSI4_DATADIR")
        if psi4_datadir and Path(psi4_datadir).is_dir():
            basis_dir = Path(psi4_datadir)
        else:
            logger.warning(
                f"[bootstrap] PSI4_DATADIR ('{psi4_datadir}') is not set or not a directory. Falling back..."
            )
    except Exception as e:
        logger.debug(
            f"[bootstrap] Could not get PSI4_DATADIR via psi4.core.get_global_option: {e!s}. Falling back..."
        )

    if basis_dir is None:  # Fallback if PSI4_DATADIR failed
        try:
            prefix_path = Path(sys.prefix)
            conda_basis_dir = prefix_path / "share" / "psi4" / "basis"
            if conda_basis_dir.is_dir():
                basis_dir = conda_basis_dir
                logger.info(f"[bootstrap] Using basis directory from sys.prefix: {basis_dir}")
            else:  # Last resort: try CONDA_PREFIX if available
                if "CONDA_PREFIX" in os.environ:
                    conda_prefix_dir = Path(os.environ["CONDA_PREFIX"]) / "share" / "psi4" / "basis"
                    if conda_prefix_dir.is_dir():
                        basis_dir = conda_prefix_dir
                        logger.info(
                            f"[bootstrap] Using basis directory from CONDA_PREFIX: {basis_dir}"
                        )
                    else:
                        logger.error(
                            f"[bootstrap] Fallback basis directory {conda_prefix_dir} also not found."
                        )
                else:
                    logger.error(
                        "[bootstrap] CONDA_PREFIX not set, cannot find fallback basis directory."
                    )
        except Exception as e:
            logger.error(f"[bootstrap] Error constructing fallback basis directory path: {e!s}")

    if basis_dir is None:
        logger.error(
            "[bootstrap] Could not determine Psi4 basis directory. Skipping basis installation."
        )
        return

    if not basis_dir.exists():
        logger.warning(f"[bootstrap] Basis directory {basis_dir} missing; creating.")
        try:
            basis_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(
                f"[bootstrap] Failed to create basis directory {basis_dir}: {e!s}. Skipping basis installation."
            )
            return

    logger.info(f"[bootstrap] Using basis directory: {basis_dir}")

    installed = 0
    for b_name in requested:  # Changed loop var name to avoid conflict
        try:
            # Attempt to get canonical name, fallback to lowercased name
            try:
                canonical_check = bse.lut.get_basis_aliases(b_name)[0]
            except AttributeError:
                logger.debug(
                    f"[bootstrap] bse.lut.get_basis_aliases not found (BSE < 0.9?). Falling back to name.lower() for {b_name}"
                )
                canonical_check = b_name.lower()
            except Exception as e:
                logger.warning(
                    f"[bootstrap] Error getting alias for {b_name}: {e!s}. Using name.lower()."
                )
                canonical_check = b_name.lower()

            if (basis_dir / f"{canonical_check}.gbs").exists():
                logger.debug(
                    f"[bootstrap] Basis {canonical_check} (requested as {b_name}) already exists."
                )
                continue

            logger.info(f"[bootstrap] Attempting to install {b_name} (as {canonical_check})...")
            if _download_and_write(b_name, basis_dir):  # Pass original name to _download_and_write
                installed += 1
        except Exception as e:
            logger.error(f"[bootstrap] Unexpected error processing basis {b_name}: {e!s}")

    if installed > 0:
        logger.info(
            f"[bootstrap] Successfully installed {installed} new basis set(s). Psi4 will find them on next full init or if cache is managed externally."
        )
    else:
        logger.info(
            "[bootstrap] All requested_bases either already existed or could not be installed. No new files written by this process."
        )

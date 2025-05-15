import os
import basis_set_exchange as bse
import psi4
import logging

logger = logging.getLogger(__name__)

# Bases requested by the sweep.yml, ensuring all are covered.
REQUESTED = [
    "jul-cc-pVDZ", "jul-cc-pVTZ", "jul-cc-pVQZ",
    "jun-cc-pVDZ", "jun-cc-pVTZ", "jun-cc-pVQZ",
    "aug-cc-pVDZ", "aug-cc-pVTZ", "aug-cc-pVQZ",
    "def2-SVPD", "def2-TZVPD", "def2-QZVPD", "def2-TZVPPD",
]

def ensure_bases():
    """
    Ensures all requested basis sets are available in Psi4's search path.
    Downloads and installs them using basis_set_exchange if missing.
    """
    try:
        if "CONDA_PREFIX" not in os.environ:
            logger.warning("[bootstrap] CONDA_PREFIX not set. Cannot determine Psi4 basis directory. Skipping basis check.")
            return

        target_dir = os.path.join(os.environ["CONDA_PREFIX"], "share", "psi4", "basis")
        os.makedirs(target_dir, exist_ok=True)
        logger.info(f"[bootstrap] Checking basis sets in {target_dir}")

        installed_count = 0
        downloaded_count = 0

        for name in REQUESTED:
            gbs_path = os.path.join(target_dir, f"{name}.gbs")
            if os.path.isfile(gbs_path):
                logger.debug(f"[bootstrap] Basis set {name} already present at {gbs_path}")
                installed_count += 1
                continue
            
            logger.info(f"[bootstrap] Downloading {name}...")
            try:
                gbs_txt = bse.get_basis(
                    name,
                    fmt="psi4",
                    header=False,  # We just need the raw basis
                    optimize_cartesian=True,
                )
                with open(gbs_path, "w") as fh:
                    fh.write(gbs_txt)
                logger.info(f"[bootstrap] Successfully downloaded and saved {name} to {gbs_path}")
                downloaded_count += 1
            except Exception as e:
                logger.error(f"[bootstrap] Failed to download or save basis set {name}: {e}")

        total_requested = len(REQUESTED)
        if downloaded_count > 0:
            logger.info(f"[bootstrap] Downloaded {downloaded_count} new basis sets.")
            # Tell Psi4 to rescan its basis directory if new bases were added
            logger.info("[bootstrap] Clearing Psi4 global basis cache to recognize new files.")
            psi4.core.BasisSet.clear_global_cache()
        
        logger.info(f"[bootstrap] Basis check complete. Total requested: {total_requested}, Found/Installed: {installed_count + downloaded_count}")

    except ImportError:
        logger.error("[bootstrap] basis_set_exchange or psi4 is not installed. Cannot perform basis bootstrap.")
    except Exception as e:
        logger.error(f"[bootstrap] An unexpected error occurred during basis check: {e}") 
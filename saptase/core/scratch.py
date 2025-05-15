r"""Scratch-directory isolation helpers.

This module provides :class:`TaskScratch`, a context manager that guarantees
**per-task** scratch isolation for Psi4 (and other back-ends) while
transparently cleaning up on exit.

Rationale
---------
Real HPC clusters mount the global ``/tmp`` or ``$TMPDIR`` on the compute node
and rely on the user to keep it tidy.  When a single Dask worker executes many
SAPT tasks, leaving scratch files behind will eventually exhaust local storage
or pollute *other* jobs.

The context therefore ensures:
* A unique directory ``{scratch_root}/{task_id}`` is created.
* Environment variables ``PSI_SCRATCH`` and ``PSI_TMPDIR`` are pointed to it.
* On context exit the directory is deleted (unless ``keep_scratch=True``).

The scratch root defaults to ``$SAPTASE_SCRATCH_ROOT`` \| ``$TMPDIR`` \|
``$TEMP`` \| ``/tmp``.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class TaskScratch(contextlib.AbstractContextManager):
    """Context manager that isolates *one* task's scratch directory."""

    def __init__(
        self,
        task_id: str,
        scratch_root: Optional[str] = None,
        keep_scratch: bool = False,
    ) -> None:
        self.task_id = task_id or uuid.uuid4().hex  # fall back if not set
        self.keep_scratch = keep_scratch

        # Determine root directory precedence: env → param → platform temp → /tmp
        root = (
            scratch_root
            or os.environ.get("SAPTASE_SCRATCH_ROOT")
            or os.environ.get("TMPDIR")
            or os.environ.get("TEMP")
            or "/tmp"
        )
        self.root_path = Path(root).expanduser().resolve()
        self.dir_path = self.root_path / "saptase" / self.task_id

        # Track whether *this* context created the directory so cleanup is
        # idempotent when contexts are nested (backend + orchestrator).
        self._created_here = not self.dir_path.exists()

        # Hold previous env to restore later (per-context push/pop semantics)
        self._old_env: dict[str, Optional[str]] = {}

    # ---------------------------------------------------------------------
    # Context-manager protocol
    # ---------------------------------------------------------------------
    def __enter__(self) -> str:  # returns the directory path as *str* for convenience
        try:
            self.dir_path.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # pragma: no cover – fatal mis-configuration
            logger.error("Failed creating scratch directory %s: %s", self.dir_path, exc)
            raise

        # Swap environment variables used by Psi4 (and some other QC codes)
        for var in ("PSI_SCRATCH", "PSI_TMPDIR"):
            self._old_env[var] = os.environ.get(var)
            os.environ[var] = str(self.dir_path)

        logger.debug("Task %s using scratch dir %s", self.task_id, self.dir_path)
        return str(self.dir_path)

    def __exit__(self, exc_type, exc, tb):
        # Restore previous environment (or delete variable if absent before)
        for var, old in self._old_env.items():
            if old is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = old

        # Cleanup directory
        if self.keep_scratch:
            logger.debug("Keeping scratch dir for task %s at %s", self.task_id, self.dir_path)
            return False  # propagate exceptions, if any

        # Only the *creator* removes directory when exiting – nested contexts leave
        # cleanup responsibility to the outer-most.
        # This block is effectively the 'finally' for the scratch directory usage
        # if keep_scratch is False.
        if self._created_here:
            try:
                logger.info("Attempting to remove scratch directory for task %s at %s", self.task_id, self.dir_path)
                shutil.rmtree(self.dir_path, ignore_errors=True) # ignore_errors makes it robust
                logger.debug("Successfully initiated removal of scratch directory %s (or it didn't exist).", self.dir_path)

                # Also attempt to clean empty parent "saptase" folder (non-fatal)
                parent = self.dir_path.parent
                if parent.exists() and not any(parent.iterdir()): # Check if parent is empty and exists
                    logger.debug("Attempting to remove empty parent scratch directory %s", parent)
                    try:
                        parent.rmdir()
                        logger.info("Successfully removed empty parent scratch directory %s", parent)
                    except OSError as e_rmdir_parent: # Catch specific OS error for rmdir
                        logger.warning(
                            "Could not remove empty parent scratch directory %s: %s",
                            parent,
                            e_rmdir_parent,
                        )
            except Exception as exc_cleanup:  # pragma: no cover – catch any other unexpected error during cleanup
                # This catches errors in the cleanup logic itself, not from the 'with' block body.
                logger.error(
                    "Unexpected error during scratch directory cleanup for task %s at %s: %s",
                    self.task_id,
                    self.dir_path,
                    exc_cleanup,
                    exc_info=True # Log traceback for unexpected cleanup errors
                )
        else:
            logger.debug("Not the creator of scratch directory %s, leaving cleanup to outer context.", self.dir_path)

        return False  # never suppress exceptions from the 'with' block body

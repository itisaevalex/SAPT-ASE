"""Thin wrapper around ``dask.distributed.Client`` to provide a *local-parallel-like*
API for SAPTASE.

Purpose
-------
The rest of the codebase (orchestrator, workflows) expects something that looks
like a `concurrent.futures.Executor`: it needs a ``submit(fn, *args)`` returning
Future-like objects.  We *could* just re-use ``Client`` directly, but wrapping it
lets us hide the logic of *create a LocalCluster OR connect to existing* and
also cleanly close everything in a context manager.
"""

from __future__ import annotations

import logging
import os
import gc
import asyncio
from dask.distributed.utils import sync
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

if TYPE_CHECKING:
    from saptase.core.models import SaptTask

logger = logging.getLogger(__name__)

try:
    from dask.distributed import Client, Future, LocalCluster
except ImportError as exc:  # pragma: no cover – optional dependency missing
    raise ImportError(
        "The 'dask.distributed' package is required for Dask execution; install with `pip install \"dask[distributed]\"`."
    ) from exc


def _dummy_worker(task):  # top-level picklable helper for tests
    """Execute a task with DummyBackend inside TaskScratch (for unit tests)."""
    from saptase.core.backend import DummyBackend  # local import to avoid heavy deps
    from saptase.core.scratch import TaskScratch

    backend = DummyBackend()
    keep = task.additional_keywords.get("keep_scratch", False)
    root = task.additional_keywords.get("scratch_root")
    with TaskScratch(task.id, scratch_root=root, keep_scratch=keep) as scr:
        # create sentinel file to verify isolation in tests
        from pathlib import Path

        Path(scr).joinpath("sentinel.txt").write_text("ok")
        return backend.calculate(task)


class DaskExecutor:
    """Helper that owns a ``dask.distributed.Client`` (and optionally a Cluster)."""

    def __init__(self, scheduler: Optional[Any] = None, n_workers: Optional[int] = None):
        """Create a Dask client.

        Parameters
        ----------
        scheduler
            ``None`` ⇒ spin up an *in-process* ``LocalCluster``.  Otherwise the
            address (``"tcp://hostname:8786"``) of an existing scheduler.
        n_workers
            Number of workers when creating a *new* LocalCluster.
        """
        # Accept passing an *existing* Client instance (unit-tests convenience)
        if isinstance(scheduler, Client):
            self.client = scheduler
            self._cluster = None
            logger.debug("Using provided Dask Client instance (%s)", scheduler)

        elif scheduler is None:
            self._cluster = LocalCluster(
                n_workers=n_workers or os.cpu_count(), threads_per_worker=1
            )
            self.client = Client(self._cluster)
            logger.debug("Started LocalCluster with %d workers", len(self._cluster.workers))
        else:
            self._cluster = None
            # Attempt to connect to existing scheduler; fall back gracefully
            try:
                self.client = Client(scheduler, timeout="2s")  # type: ignore[arg-type]
                logger.debug("Connected to external Dask scheduler at %s", scheduler)
            except (OSError, TimeoutError) as exc:
                import warnings

                warnings.warn(
                    f"Dask scheduler '{scheduler}' unreachable - falling back to LocalCluster, reason: {exc}",
                    RuntimeWarning,
                )
                self._cluster = LocalCluster(
                    n_workers=n_workers or os.cpu_count(), threads_per_worker=1
                )
                self.client = Client(self._cluster)
                logger.debug(
                    "Started fallback LocalCluster with %d workers", len(self._cluster.workers)
                )

    # ---------------------------------------------------------------------
    # Proxy a couple of useful Client methods
    # ---------------------------------------------------------------------
    def submit_task(self, fn: Callable[..., Any], *args: Any) -> "Future[Any]":
        """Submit a function with *args* exactly as in ProcessPoolExecutor path."""
        return self.client.submit(fn, *args)

    def close(self) -> None:
        """Close client and *owned* cluster (if any)."""
        try:
            if self.client:
                logger.debug(
                    f"Attempting to close Dask client: {self.client.dashboard_link if hasattr(self.client, 'dashboard_link') else self.client}"
                )
                # Give client a moment to close gracefully
                self.client.close(timeout=5)
                logger.debug(f"Dask client closed.")
                self.client = None
        except Exception as client_close_err:
            logger.warning(f"Error closing Dask client: {client_close_err}")

        if self._cluster is not None:
            # Store address before potential errors/setting to None
            cluster_addr = self._cluster.scheduler_address
            logger.debug(
                f"Attempting to close owned Dask cluster: {cluster_addr}"
            )
            try:
                # Close the cluster synchronously, waiting for workers
                self._cluster.close(timeout=10)
                logger.debug(f"Closed owned Dask cluster: {cluster_addr}")
                self._cluster = None
                # Force garbage collection and allow async tasks to finish
                gc.collect()
                loop = asyncio.get_event_loop()
                # Use standard asyncio run_until_complete
                loop.run_until_complete(asyncio.sleep(0.2))
            except Exception as cluster_close_err:
                logger.warning(
                    # Use stored address here
                    f"Error closing owned Dask cluster {cluster_addr}: {cluster_close_err}"
                )
        else:
            logger.debug("No owned Dask cluster to close.")

    # We support ``with DaskExecutor(...) as ex:``
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    # Convenience for tests
    def __getattr__(self, item):  # proxy everything else to Client
        return getattr(self.client, item)

    # ------------------------------------------------------------------
    # Simple helper for unit tests – run list[SaptTask] with DummyBackend
    # ------------------------------------------------------------------
    def run_tasks(self, tasks: List["SaptTask"]):
        """Execute tasks and wait for completion (DummyBackend)."""
        from dask.distributed import as_completed

        from saptase.core.models import SaptResult

        futures = {self.submit_task(_dummy_worker, t): t.id for t in tasks}
        results: Dict[str, "SaptResult"] = {}
        for fut in as_completed(futures):
            tid = futures[fut]
            try:
                res = fut.result()
            except Exception as exc:  # pragma: no cover
                import warnings

                warnings.warn(f"Task {tid} raised {exc}")
                res = None
            results[tid] = res
        return results

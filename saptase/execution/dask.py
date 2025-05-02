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
import time
import inspect # Added for isawaitable
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
        self._cluster: Optional[LocalCluster] = None # Explicitly type hint
        self.client: Optional[Client] = None # Explicitly type hint

        # Accept passing an *existing* Client instance (unit-tests convenience)
        if isinstance(scheduler, Client):
            self.client = scheduler
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
        if not self.client:
            raise RuntimeError("DaskExecutor has been closed and cannot submit tasks.")
        return self.client.submit(fn, *args)

    async def close(self) -> None:
        """
        Coroutine that **awaits** full shutdown of the client *and* cluster.
        Making this async is crucial because `LocalCluster.close()` is itself
        asynchronous – it returns before the scheduler & workers are gone.
        """
        if self.client:
            # Client.close is synchronous
            # Wrap in try/except as it might raise if already closed/closing
            try:
                self.client.close(timeout=5) # Keep timeout for client
                logger.debug(f"Dask client closed.")
            except Exception as client_close_err:
                 logger.warning(f"Error closing Dask client (might be expected if cluster shut down first): {client_close_err}")
            finally:
                self.client = None

        if self._cluster:
            cluster_to_close = self._cluster
            cluster_addr = "unknown" # Default in case of early error
            try:
                cluster_addr = cluster_to_close.scheduler_address
                logger.debug(f"Attempting to await close for owned Dask cluster: {cluster_addr}")
                # LocalCluster.close() is *sometimes* a coroutine, sometimes None.
                maybe_coro = cluster_to_close.close() 
                if inspect.isawaitable(maybe_coro):
                    await maybe_coro
                    logger.debug(f"Successfully awaited close for owned Dask cluster: {cluster_addr}")
                else:
                     # synchronous path – give Dask's background threads a moment
                    logger.debug(f"Cluster close returned None (synchronous); adding small sleep.")
                    await asyncio.sleep(0.05)

                # wait (max 5 s) for weak-ref to disappear from LocalCluster._instances
                deadline = time.monotonic() + 5.0
                while cluster_to_close in getattr(LocalCluster, "_instances", set()):
                    if time.monotonic() > deadline:
                        logger.warning(
                            f"LocalCluster {cluster_addr} still present in _instances after 5 s timeout."
                        )
                        break
                    #logger.debug(f"Polling: Cluster {cluster_addr} still in _instances...") # Verbose
                    gc.collect()
                    await asyncio.sleep(0.05)
                else:
                    logger.debug(f"Polling: Cluster {cluster_addr} successfully removed from _instances.")

            except Exception as cluster_close_err:
                logger.warning(f"Error awaiting/polling close for owned Dask cluster {cluster_addr}: {cluster_close_err}")
            finally:
                # drop our strong reference so GC can reap the object
                self._cluster = None
                # Encourage weak-ref cleanup *now*, so _instances clears promptly
                gc.collect()
        else:
            logger.debug("No owned Dask cluster to close.")

    # We support ``with DaskExecutor(...) as ex:``
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        # Run the async close method synchronously
        try:
            asyncio.run(self.close())
        except RuntimeError as e:
            # Handle cases where asyncio.run() cannot be called (e.g., loop already running)
            # In such cases, maybe log a warning or try a different approach if needed.
            # For now, just log if running into issues.
            logger.error(f"Error running async close in DaskExecutor.__exit__: {e}")

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

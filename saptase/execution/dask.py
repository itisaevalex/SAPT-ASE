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

import asyncio
import gc
import inspect  # Added for isawaitable
import logging
import os
import time
import weakref  # Potentially needed for handler cleanup logic
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from dask.distributed.comm.core import CommClosedError
from dask.distributed.utils import sync

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


# New robust helper function based on supervisor recommendation
async def really_close(
    client: Optional[Client], cluster: Optional[LocalCluster], timeout: float = 5.0
):
    """Robustly close Client and LocalCluster, waiting for scheduler completion."""
    if not client and not cluster:
        logger.debug("really_close: Nothing to close.")
        return

    cluster_addr = "unknown"
    # Capture the initial cluster argument. This reference is used for weakref logic later.
    _original_cluster_passed_in = cluster 

    if cluster: # Use the mutable 'cluster' for direct ops, _original_cluster_passed_in for weakref
        try:
            cluster_addr = cluster.scheduler_address
        except Exception:
            pass  # Already closed or inaccessible

    logger.debug(f"really_close: Starting shutdown for cluster {cluster_addr}")

    # 1. Flush computations and close client
    if client:
        try:
            futures = list(client.futures.values())  # Get outstanding futures
            if futures:
                logger.debug(
                    f"really_close: Cancelling {len(futures)} outstanding futures for client {client}"
                )
                await client.cancel(futures, force=True)
                await asyncio.sleep(0.01)  # Give cancel a moment
            await client.close(timeout=5)
            logger.debug(f"really_close: Client closed for cluster {cluster_addr}")
        except Exception as e:
            logger.warning(f"really_close: Error closing client for {cluster_addr}: {e}")
        finally:
            # Ensure client reference is removed for GC
            client = None
            del client  # Explicit delete just in case

    # 2. Close cluster and wait for scheduler to finish async teardown
    if cluster:
        try:
            # Now close the cluster itself
            logger.debug(f"really_close: Closing cluster {cluster_addr}")
            # Check if close returns awaitable, handle both cases
            maybe_coro = cluster.close()
            if inspect.isawaitable(maybe_coro):
                logger.debug(f"really_close: Awaiting async cluster.close() for {cluster_addr}")
                await maybe_coro
                logger.debug(f"really_close: Finished awaiting cluster.close() for {cluster_addr}")
            else:
                # Sync close called, proceed to wait for scheduler
                logger.debug(f"really_close: Sync close called for {cluster_addr}")

            # Re-fetch scheduler in case cluster.close() replaced it
            scheduler = getattr(cluster, "scheduler", None)
            if scheduler and hasattr(scheduler, "finished"):
                logger.debug(f"really_close: Waiting for scheduler.finished() for {cluster_addr}")
                await asyncio.wait_for(scheduler.finished(), timeout=timeout)
                logger.debug(f"really_close: Scheduler finished for {cluster_addr}")

        except CommClosedError:
            logger.debug(
                f"really_close: Cluster {cluster_addr} CommClosedError during close/wait (likely already closing)."
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"really_close: Scheduler for {cluster_addr} did not finish within {timeout:.1f}s timeout."
            )
        except Exception as e:
            logger.warning(
                f"really_close: Error during cluster close/scheduler wait for {cluster_addr}: {e}"
            )

    # 3. Extra: stop dashboard if it exists (belt and suspenders)
    if _original_cluster_passed_in:  # Use original ref here
        http_server = getattr(_original_cluster_passed_in, "_http_server", None)
        if http_server:
            try:
                http_server.stop()
                logger.debug(f"really_close: Stopped dashboard http_server for {cluster_addr}")
            except Exception as e:
                logger.warning(
                    f"really_close: Error stopping dashboard http_server for {cluster_addr}: {e}"
                )
        # Clear ref to server
        http_server = None

    # 4. Final GC sweep and polling using weak reference
    logger.debug(f"really_close: Starting final GC sweep for {cluster_addr}")
    # Clear local strong references that might hold onto the cluster object
    maybe_coro = None
    scheduler = None
    futures = None
    # Explicitly clear the 'cluster' variable which might have been used for direct operations.
    # _original_cluster_passed_in holds the reference needed for weakref logic if it existed.
    cluster = None 

    if _original_cluster_passed_in is not None:
        # Create weak reference to the cluster object that was originally passed in
        cluster_to_weakref = _original_cluster_passed_in
        cluster_ref = weakref.ref(cluster_to_weakref)
        
        # Attempt to remove the strong reference held by the argument itself.
        # This helps if this function call was the last holder of the strong reference.
        del _original_cluster_passed_in
        # No need to del cluster_to_weakref here, it's just a temporary pointer for clarity.

        # Run GC passes
        gc.collect()
        await asyncio.sleep(0.01)  # Yield after first collect
        gc.collect()
        await asyncio.sleep(0.05)  # Short sleep after second collect

        # Poll using the weak reference
        if cluster_ref() is not None:
            logger.debug(
                f"Polling: Cluster {cluster_addr} still referenced after GC sweep, starting weakref poll..."
            )
            deadline = time.monotonic() + timeout  # Reuse timeout for poll
            while cluster_ref() is not None and time.monotonic() < deadline:
                gc.collect()
                await asyncio.sleep(0.05)
                # Check if the weakref became None
            if cluster_ref() is not None:
                # Check _instances one last time for logging clarity
                final_instances = getattr(LocalCluster, "_instances", set())
                # Use cluster_to_weakref here if cluster_ref() is not None, as it's the object.
                # However, the object from cluster_ref() is the canonical way.
                if obj_from_ref := cluster_ref(): # Get the object from the weakref
                    if obj_from_ref in final_instances:
                        logger.info(
                            f"Leak-guard: Cluster {cluster_addr} weakref STILL alive and in _instances after final cleanup and polling!"
                        )
                    else:
                        logger.warning(
                            f"Leak-guard: Cluster {cluster_addr} weakref still alive but NOT in _instances after polling."
                        )
            else:
                logger.debug(f"Polling: Cluster {cluster_addr} weakref cleared during poll.")
        else:
            logger.debug(f"Polling: Cluster {cluster_addr} weakref already cleared before final poll.")

        # Explicitly remove from _instances as a final safeguard
        if alive_cluster_obj := cluster_ref():  # Get object if weakref still alive
            if hasattr(LocalCluster, "_instances"):
                try:
                    instances_set = getattr(LocalCluster, "_instances")
                    if alive_cluster_obj in instances_set:
                        logger.warning(
                            f"really_close: Explicitly removing cluster {cluster_addr} from _instances after polling."
                        )
                        instances_set.discard(alive_cluster_obj)
                except Exception as e:
                    logger.error(f"Error during final explicit _instances.discard: {e}")

        # Clean up the weakref object itself
        del cluster_ref
    else:
        logger.debug(f"really_close: No cluster object provided (_original_cluster_passed_in was None). Skipping weakref-based cleanup for cluster.")

    gc.collect()  # One last collect
    logger.debug(f"really_close: Finished cleanup sequence for cluster {cluster_addr}")


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
        self._cluster: Optional[LocalCluster] = None  # Explicitly type hint
        self.client: Optional[Client] = None  # Explicitly type hint

        # Accept passing an *existing* Client instance (unit-tests convenience)
        if isinstance(scheduler, Client):
            self.client = scheduler
            logger.debug("Using provided Dask Client instance (%s)", scheduler)

        elif scheduler is None:
            self._cluster = LocalCluster(
                n_workers=n_workers or os.cpu_count(),
                threads_per_worker=1,
                # Disable all background servers for reliability in tests
                dashboard_address=None,
                diagnostics_port=None,
                services={},
            )
            self.client = Client(self._cluster)
            logger.debug(
                "Started LocalCluster with %d workers (all diagnostic services disabled)",
                len(self._cluster.workers),
            )
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
        Coroutine that robustly shuts down the client and owned cluster.
        Delegates to the really_close helper function.
        """
        client_to_close = self.client
        cluster_to_close = self._cluster

        # Clear attributes immediately to prevent reuse
        self.client = None
        self._cluster = None

        try:
            await really_close(client_to_close, cluster_to_close)  # Call the robust helper
        except Exception as e:
            # Log error from the helper, but ensure flow continues
            logger.error(f"Error encountered in DaskExecutor.close calling really_close: {e}")
        finally:
            # Ensure attributes are None and encourage GC
            self.client = None
            self._cluster = None
            # No need to delete client_to_close/cluster_to_close here, they go out of scope
            gc.collect()

    # We support ``with DaskExecutor(...) as ex:``
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        # Use dask.distributed.utils.sync to run the async close method
        # Get the loop from the client *before* calling close()
        loop = None
        cluster_to_clean = self._cluster  # Keep ref for final cleanup attempt
        client_to_clean = self.client

        if client_to_clean and hasattr(client_to_clean, "loop"):
            loop = client_to_clean.loop

        if loop:
            try:
                # Run self.close() within Dask's event loop and wait
                logger.debug("DaskExecutor.__exit__: Attempting sync(loop, self.close)...")
                sync(loop, self.close)
                logger.debug("DaskExecutor.__exit__: sync(loop, self.close) completed.")
            except Exception as e:
                logger.error(
                    f"Error running async close via dask.utils.sync in DaskExecutor.__exit__: {e}",
                    exc_info=True,
                )
                # Fall through to manual cleanup if sync fails
        else:
            logger.warning(
                "Could not obtain Dask client loop in __exit__, proceeding to manual cleanup."
            )

        # --- Manual Cleanup Fallback / Final Check ---
        # This runs if loop wasn't found OR if sync failed (error logged above)
        logger.debug("DaskExecutor.__exit__: Entering manual cleanup phase.")
        try:
            if client_to_clean:
                logger.debug(f"__exit__ manual cleanup: Closing client {client_to_clean}")
                client_to_clean.close(timeout=2)  # Short timeout sync close
                self.client = None  # Ensure instance variable is cleared
            else:
                logger.debug("__exit__ manual cleanup: No client object to close.")

            if cluster_to_clean:
                logger.debug(
                    f"__exit__ manual cleanup: Checking/removing cluster {cluster_to_clean} from _instances"
                )
                if hasattr(LocalCluster, "_instances"):
                    instances_set = getattr(LocalCluster, "_instances")
                    if cluster_to_clean in instances_set:
                        instances_set.discard(cluster_to_clean)
                        logger.debug("__exit__ manual cleanup: Removed cluster from _instances.")
                    else:
                        logger.debug(
                            "__exit__ manual cleanup: Cluster already gone from _instances."
                        )
                else:
                    logger.warning(
                        "__exit__ manual cleanup: LocalCluster has no _instances attribute?"
                    )
                self._cluster = None  # Ensure instance variable is cleared
            else:
                logger.debug("__exit__ manual cleanup: No cluster object to clean.")

        except Exception as e:
            logger.error(
                f"Error during manual cleanup in DaskExecutor.__exit__: {e}", exc_info=True
            )
        finally:
            # Final guarantee: set instance vars to None and GC
            self.client = None
            self._cluster = None
            gc.collect()
            logger.debug("DaskExecutor.__exit__: Finished.")

    # Convenience for tests
    def __getattr__(self, item):  # proxy everything else to Client
        # Check if client exists before getattr to avoid AttributeError after close
        if self.client:
            try:
                return getattr(self.client, item)
            except AttributeError:
                # Re-raise if attribute truly doesn't exist on client
                raise AttributeError(
                    f"'{type(self.client).__name__}' object has no attribute '{item}'"
                )
        else:
            # Raise an error if trying to access attributes after close
            raise RuntimeError("DaskExecutor has been closed.")

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

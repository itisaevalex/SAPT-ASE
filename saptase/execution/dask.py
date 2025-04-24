"""Thin wrapper around ``dask.distributed.Client`` to provide a *local‑parallel‑like*
API for SAPTASE.

Purpose
-------
The rest of the codebase (orchestrator, workflows) expects something that looks
like a `concurrent.futures.Executor`: it needs a ``submit(fn, *args)`` returning
Future‑like objects.  We *could* just re‑use ``Client`` directly, but wrapping it
lets us hide the logic of *create a LocalCluster OR connect to existing* and
also cleanly close everything in a context manager.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

try:
    from dask.distributed import Client, LocalCluster, Future
except ImportError as exc:  # pragma: no cover – optional dependency missing
    raise ImportError(
        "The 'dask.distributed' package is required for Dask execution; install with `pip install \"dask[distributed]\"`."
    ) from exc


class DaskExecutor:
    """Helper that owns a ``dask.distributed.Client`` (and optionally a Cluster)."""

    def __init__(self, scheduler: Optional[str] = None, n_workers: Optional[int] = None):
        """Create a Dask client.

        Parameters
        ----------
        scheduler
            ``None`` ⇒ spin up an *in‑process* ``LocalCluster``.  Otherwise the
            address (``"tcp://hostname:8786"``) of an existing scheduler.
        n_workers
            Number of workers when creating a *new* LocalCluster.
        """
        if scheduler is None:
            self._cluster = LocalCluster(n_workers=n_workers or os.cpu_count(), threads_per_worker=1)
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
                    f"Dask scheduler '{scheduler}' unreachable – falling back to LocalCluster, reason: {exc}",
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

    def close(self) -> None:  # noqa: D401 (simple verb OK)
        """Close client and *owned* cluster (if any)."""
        try:
            self.client.close()
        finally:
            if self._cluster is not None:
                self._cluster.close()

    # We support ``with DaskExecutor(...) as ex:``
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    # Convenience for tests
    def __getattr__(self, item):  # proxy everything else to Client
        return getattr(self.client, item)

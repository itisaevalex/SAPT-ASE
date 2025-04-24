"""SLURM cluster helper for SAPTASE distributed execution.

This thin wrapper creates a ``dask_jobqueue.SLURMCluster`` with sensible
defaults and returns *both* the cluster object and a connected
``dask.distributed.Client`` so callers can immediately submit work.

The dependency on *dask_jobqueue* is **optional** – if it is missing we raise
``ImportError`` with a clear message that the user can install the extra with

``pip install "dask_jobqueue"``.
"""

from __future__ import annotations

from typing import Any, Tuple

# NOTE: we purposely import inside the helper so that merely importing this
# module does **not** require dask_jobqueue, allowing unit-tests to skip when
# the optional dependency is absent.


def create_slurm_cluster(
    *,
    cores: int = 4,
    memory: str = "4GB",
    walltime: str = "02:00:00",
    interface: str = "ib0",
    queue: str | None = None,
    n_workers: int | None = None,
    **extra: Any,
) -> Tuple["SLURMCluster", "Client"]:
    """Spin-up a *SLURM* backed Dask cluster.

    Parameters
    ----------
    cores
        Number of CPU cores per *worker* (``--cpus-per-task``).
    memory
        Memory per *worker* (string accepted by *dask_jobqueue*, e.g. ``"8GB"``).
    walltime
        Maximum wall-time per job in ``HH:MM:SS``.
    interface
        Network interface to advertise to the scheduler.  HPC clusters often
        need ``ib0`` or similar for high-speed Infiniband.
    queue
        Slurm partition / queue name.  If ``None`` we rely on the site default.
    n_workers
        Initial number of workers to start (defaults to *one* so users do not
        accidentally swamp the cluster).  The returned ``Client`` can always be
        scaled later via ``client.cluster.scale``.
    extra
        Keyword arguments forwarded verbatim to ``SLURMCluster`` allowing users
        to tweak advanced options (env, account, job_extra, etc.).

    Returns
    -------
    (cluster, client)
        A 2-tuple containing the *running* ``SLURMCluster`` instance and a
        connected ``dask.distributed.Client``.
    """

    try:
        from dask.distributed import Client
        from dask_jobqueue import SLURMCluster  # type: ignore
    except ImportError as exc:  # pragma: no cover – optional dep missing
        raise ImportError(
            "The optional dependency 'dask_jobqueue' is required for SLURM support. "
            'Install it via `pip install "dask_jobqueue"`.'
        ) from exc

    # Build kwargs – mapping names as *dask_jobqueue* expects.
    cluster_kwargs: dict[str, Any] = {
        "cores": cores,
        "memory": memory,
        "walltime": walltime,
        "interface": interface,
        "job_cpu": cores,  # Request same cores per node as task – avoids oversubscription
    }
    if queue is not None:
        cluster_kwargs["queue"] = queue

    # Allow caller to override any of the defaults.
    cluster_kwargs.update(extra)

    cluster = SLURMCluster(**cluster_kwargs)

    # Start an initial worker pool unless the user explicitly requested zero.
    if n_workers is None:
        n_workers = 1
    if n_workers > 0:
        cluster.scale(n_workers)

    client = cluster.get_client()
    return cluster, client

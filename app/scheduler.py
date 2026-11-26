"""Job registry the legacy ``jobs/`` scripts are being migrated onto.

A job is a plain function decorated with :func:`job`. It receives a
:class:`JobContext` and returns a :class:`JobResult`. The registry is what the
scheduler (and the ``/ops/jobs`` endpoints) enumerate, so migrating a legacy
script means: move its logic into a function here (or a module under
``app/jobs/``), register it, and delete the script.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import UTC, datetime

log = logging.getLogger("payments.jobs")

DEFAULT_TIMEOUT_SECONDS = 30.0


class JobAlreadyRunningError(RuntimeError):
    """Raised when a run is requested for a job that is still running."""


class JobTimeoutError(TimeoutError):
    """Raised when a job does not finish within its time limit."""


@dataclass(frozen=True)
class JobContext:
    now: datetime
    dry_run: bool = True


@dataclass
class JobResult:
    processed: int = 0
    notes: list[str] = field(default_factory=list)


JobFn = Callable[[JobContext], JobResult]


@dataclass(frozen=True)
class JobSpec:
    name: str
    schedule: str
    fn: JobFn
    description: str
    timeout: float = DEFAULT_TIMEOUT_SECONDS


_registry: dict[str, JobSpec] = {}
_locks: dict[str, threading.Lock] = {}


def job(
    name: str,
    *,
    schedule: str,
    description: str = "",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Callable[[JobFn], JobFn]:
    """Register ``fn`` under ``name`` with a cron-style ``schedule``.

    ``timeout`` is the longest a single run may take, in seconds.
    """

    def decorator(fn: JobFn) -> JobFn:
        if name in _registry:
            raise ValueError(f"job {name!r} already registered")
        _registry[name] = JobSpec(
            name=name, schedule=schedule, fn=fn, description=description, timeout=timeout
        )
        _locks[name] = threading.Lock()
        return fn

    return decorator


def registered_jobs() -> list[JobSpec]:
    return sorted(_registry.values(), key=lambda j: j.name)


def run_job(name: str, *, dry_run: bool = True) -> JobResult:
    """Run ``name`` once in a worker thread and wait up to its timeout.

    Only one run of a job can be active at a time: a second request while a run
    is in progress raises :class:`JobAlreadyRunningError`. A run that exceeds
    the job's timeout raises :class:`JobTimeoutError`; the job keeps its lock
    until that run actually finishes, so it cannot overlap with a new run.
    """
    spec = _registry[name]
    lock = _locks[name]
    if not lock.acquire(blocking=False):
        raise JobAlreadyRunningError(f"job {name!r} is already running")

    ctx = JobContext(now=datetime.now(UTC), dry_run=dry_run)
    future: Future[JobResult] = Future()

    def worker() -> None:
        try:
            future.set_result(spec.fn(ctx))
        except BaseException as exc:
            future.set_exception(exc)
        finally:
            lock.release()

    log.info("job.start", extra={"job": name, "dry_run": dry_run})
    try:
        threading.Thread(target=worker, name=f"job-{name}", daemon=True).start()
    except BaseException:
        lock.release()
        raise
    try:
        result = future.result(timeout=spec.timeout)
    except TimeoutError as exc:
        log.error("job.timeout", extra={"job": name, "timeout": spec.timeout})
        raise JobTimeoutError(f"job {name!r} did not finish within {spec.timeout}s") from exc
    log.info("job.done", extra={"job": name, "processed": result.processed})
    return result

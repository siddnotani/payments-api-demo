"""Job registry the legacy ``jobs/`` scripts are being migrated onto.

A job is a plain function decorated with :func:`job`. It receives a
:class:`JobContext` and returns a :class:`JobResult`. The registry is what the
scheduler (and the ``/ops/jobs`` endpoints) enumerate, so migrating a legacy
script means: move its logic into a function here (or a module under
``app/jobs/``), register it, and delete the script.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

log = logging.getLogger("payments.jobs")


@dataclass(frozen=True)
class JobContext:
    now: datetime
    dry_run: bool = False


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


_registry: dict[str, JobSpec] = {}


def job(name: str, *, schedule: str, description: str = "") -> Callable[[JobFn], JobFn]:
    """Register ``fn`` under ``name`` with a cron-style ``schedule``."""

    def decorator(fn: JobFn) -> JobFn:
        if name in _registry:
            raise ValueError(f"job {name!r} already registered")
        _registry[name] = JobSpec(name=name, schedule=schedule, fn=fn, description=description)
        return fn

    return decorator


def registered_jobs() -> list[JobSpec]:
    return sorted(_registry.values(), key=lambda j: j.name)


def run_job(name: str, *, dry_run: bool = False) -> JobResult:
    spec = _registry[name]
    ctx = JobContext(now=datetime.now(UTC), dry_run=dry_run)
    log.info("job.start", extra={"job": name, "dry_run": dry_run})
    result = spec.fn(ctx)
    log.info("job.done", extra={"job": name, "processed": result.processed})
    return result

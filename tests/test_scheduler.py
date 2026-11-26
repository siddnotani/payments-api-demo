import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import scheduler
from app.main import app
from app.scheduler import (
    JobAlreadyRunningError,
    JobContext,
    JobResult,
    JobTimeoutError,
    job,
    run_job,
)

client = TestClient(app)


@pytest.fixture
def temp_job():
    """Register throwaway jobs for one test and remove them afterwards."""
    names: list[str] = []

    def register(name, fn, **kwargs):
        job(name, schedule="* * * * *", **kwargs)(fn)
        names.append(name)

    yield register
    for name in names:
        scheduler._registry.pop(name, None)
        scheduler._locks.pop(name, None)


def test_job_context_defaults_to_dry_run():
    assert JobContext(now=None).dry_run is True


def test_run_job_defaults_to_dry_run(temp_job):
    seen: list[bool] = []

    def record(ctx: JobContext) -> JobResult:
        seen.append(ctx.dry_run)
        return JobResult()

    temp_job("record_dry_run", record)
    run_job("record_dry_run")
    run_job("record_dry_run", dry_run=False)
    assert seen == [True, False]


def test_run_job_heartbeat_defaults_to_dry_run(monkeypatch):
    seen: list[bool] = []
    spec = scheduler._registry["heartbeat"]

    def record(ctx: JobContext) -> JobResult:
        seen.append(ctx.dry_run)
        return spec.fn(ctx)

    monkeypatch.setitem(
        scheduler._registry, "heartbeat", spec.__class__(**{**vars(spec), "fn": record})
    )
    run_job("heartbeat")
    assert seen == [True]


def _blocking_job(started: threading.Event, release: threading.Event):
    def fn(ctx: JobContext) -> JobResult:
        started.set()
        release.wait(5)
        return JobResult(processed=1)

    return fn


def test_concurrent_run_of_same_job_is_refused(temp_job):
    started, release = threading.Event(), threading.Event()
    temp_job("slow", _blocking_job(started, release))

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(client.post, "/ops/jobs/slow/run")
        assert started.wait(5)
        second = client.post("/ops/jobs/slow/run", params={"dry_run": "false"})
        assert second.status_code == 409
        assert "already running" in second.json()["detail"]
        release.set()
        assert first.result(5).status_code == 200

    assert client.post("/ops/jobs/slow/run").status_code == 200


def test_other_jobs_run_while_one_is_running(temp_job):
    started, release = threading.Event(), threading.Event()
    temp_job("slow_a", _blocking_job(started, release))

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(run_job, "slow_a")
        assert started.wait(5)
        assert client.post("/ops/jobs/heartbeat/run").status_code == 200
        release.set()
        assert first.result(5).processed == 1


def test_job_exceeding_timeout_returns_504_and_keeps_lock(temp_job):
    started, release = threading.Event(), threading.Event()
    temp_job("hangs", _blocking_job(started, release), timeout=0.1)

    response = client.post("/ops/jobs/hangs/run")
    assert response.status_code == 504
    assert "did not finish" in response.json()["detail"]

    # The timed-out run is still going, so a new run must not overlap with it.
    with pytest.raises(JobAlreadyRunningError):
        run_job("hangs")

    release.set()
    deadline = time.monotonic() + 5
    while scheduler._locks["hangs"].locked() and time.monotonic() < deadline:
        time.sleep(0.01)
    release.clear()
    started.clear()
    with pytest.raises(JobTimeoutError):
        run_job("hangs")
    release.set()


def test_job_errors_propagate_and_release_lock(temp_job):
    calls = {"n": 0}

    def boom(ctx: JobContext) -> JobResult:
        calls["n"] += 1
        raise RuntimeError("boom")

    temp_job("boom", boom)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="boom"):
            run_job("boom")
    assert calls["n"] == 2

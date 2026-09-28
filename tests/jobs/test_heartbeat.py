from datetime import UTC, datetime

from app.jobs.heartbeat import heartbeat
from app.scheduler import JobContext, registered_jobs


def test_heartbeat_is_registered():
    assert "heartbeat" in {j.name for j in registered_jobs()}


def test_heartbeat_reports_time():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    result = heartbeat(JobContext(now=now, dry_run=True))
    assert result.processed == 0
    assert result.notes == ["alive at 2026-01-01T00:00:00+00:00"]

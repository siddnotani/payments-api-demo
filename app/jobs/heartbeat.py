"""Reference job: the shape every migrated legacy script should end up in."""

from app.scheduler import JobContext, JobResult, job


@job("heartbeat", schedule="*/5 * * * *", description="Proves the scheduler is alive.")
def heartbeat(ctx: JobContext) -> JobResult:
    return JobResult(processed=0, notes=[f"alive at {ctx.now.isoformat()}"])

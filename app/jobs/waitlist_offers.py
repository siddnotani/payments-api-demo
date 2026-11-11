"""Scheduling jobs: expire overdue seat offers and relay the outbox to legacy tables."""

from app.scheduler import JobContext, JobResult, job
from app.scheduling import expire_offers, relay_outbox


@job(
    "waitlist-offer-expiry",
    schedule="*/5 * * * *",
    description="Expires overdue seat offers and offers the seat to the next candidate.",
)
def waitlist_offer_expiry(ctx: JobContext) -> JobResult:
    count = expire_offers(ctx.now, dry_run=ctx.dry_run)
    verb = "would expire" if ctx.dry_run else "expired"
    return JobResult(processed=count, notes=[f"{verb} {count} offer(s)"])


@job(
    "scheduling-outbox-relay",
    schedule="* * * * *",
    description="Projects scheduling outbox events into legacy Booking / Waitlist.",
)
def scheduling_outbox_relay(ctx: JobContext) -> JobResult:
    count = relay_outbox(dry_run=ctx.dry_run)
    verb = "would relay" if ctx.dry_run else "relayed"
    return JobResult(processed=count, notes=[f"{verb} {count} event(s)"])

"""In-app scheduled jobs. Import modules here so they register on startup."""

from app.jobs import heartbeat  # noqa: F401

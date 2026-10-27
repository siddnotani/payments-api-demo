"""In-app notifications for payment events.

Notifications are stored in memory alongside transactions; there is no
external delivery (email/SMS). Recipients are account identifiers.
"""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel


class NotificationType(StrEnum):
    TRANSACTION_CREATED = "transaction.created"
    TRANSACTION_SUCCEEDED = "transaction.succeeded"
    TRANSACTION_FAILED = "transaction.failed"


class Notification(BaseModel):
    id: str
    recipient: str
    type: NotificationType
    message: str
    transaction_id: str | None = None
    read: bool = False
    created_at: datetime


_notifications: dict[str, Notification] = {}


def reset_store() -> None:
    """Clear all stored notifications (used by tests)."""
    _notifications.clear()


def create_notification(
    recipient: str,
    type: NotificationType,
    message: str,
    transaction_id: str | None = None,
) -> Notification:
    notification = Notification(
        id=str(uuid4()),
        recipient=recipient,
        type=type,
        message=message,
        transaction_id=transaction_id,
        created_at=datetime.now(UTC),
    )
    _notifications[notification.id] = notification
    return notification


def list_notifications(recipient: str) -> list[Notification]:
    """Notifications for ``recipient``, newest first."""
    return [n for n in reversed(_notifications.values()) if n.recipient == recipient]


def get_notification(notification_id: str, recipient: str) -> Notification | None:
    notification = _notifications.get(notification_id)
    if notification is None or notification.recipient != recipient:
        return None
    return notification


def mark_read(notification_id: str, recipient: str) -> Notification | None:
    notification = get_notification(notification_id, recipient)
    if notification is not None:
        notification.read = True
    return notification

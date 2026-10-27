import pytest
from fastapi.testclient import TestClient

from app import notifications
from app.main import Transaction, TransactionStatus, _notify_transaction, app, reset_store
from app.notifications import NotificationType

client = TestClient(app)

PAYER = "ES9121000418450200051332"
PAYEE = "GB29NWBK60161331926819"

SAMPLE_TX = {
    "from_account": PAYER,
    "to_account": PAYEE,
    "amount": "125.50",
    "currency": "EUR",
    "reference": "Invoice 42",
}


@pytest.fixture(autouse=True)
def clean_store():
    reset_store()
    yield
    reset_store()


def _list(recipient):
    response = client.get("/notifications", params={"recipient": recipient})
    assert response.status_code == 200
    return response.json()


def test_list_notifications_empty():
    assert _list(PAYER) == []


def test_create_transaction_notifies_payer_and_payee():
    tx = client.post("/transactions", json=SAMPLE_TX).json()

    payer = _list(PAYER)
    assert [n["type"] for n in payer] == ["transaction.succeeded", "transaction.created"]
    assert [n["message"] for n in payer] == [
        "Payment of 125.50 EUR sent",
        "Payment of 125.50 EUR created",
    ]
    assert all(n["transaction_id"] == tx["id"] for n in payer)
    assert all(n["recipient"] == PAYER for n in payer)
    assert all(n["read"] is False for n in payer)
    assert all(n["id"] and n["created_at"] for n in payer)

    payee = _list(PAYEE)
    assert len(payee) == 1
    assert payee[0]["type"] == "transaction.succeeded"
    assert payee[0]["message"] == "Payment of 125.50 EUR received"
    assert payee[0]["transaction_id"] == tx["id"]


def test_rejected_transaction_creates_no_notifications():
    response = client.post("/transactions", json={**SAMPLE_TX, "to_account": PAYER})
    assert response.status_code == 422
    assert _list(PAYER) == []


def test_pending_transaction_only_notifies_created():
    tx = Transaction(
        id="tx-pending",
        status=TransactionStatus.PENDING,
        created_at="2026-01-01T00:00:00Z",
        **SAMPLE_TX,
    )
    _notify_transaction(tx)
    assert [n["type"] for n in _list(PAYER)] == ["transaction.created"]
    assert _list(PAYEE) == []


def test_list_notifications_newest_first():
    first = client.post("/transactions", json=SAMPLE_TX).json()
    second = client.post("/transactions", json={**SAMPLE_TX, "amount": "10.00"}).json()
    ids = [n["transaction_id"] for n in _list(PAYEE)]
    assert ids == [second["id"], first["id"]]


def test_list_notifications_requires_recipient():
    assert client.get("/notifications").status_code == 422
    assert client.get("/notifications", params={"recipient": ""}).status_code == 422


def test_mark_notification_read():
    client.post("/transactions", json=SAMPLE_TX)
    target = _list(PAYEE)[0]

    response = client.post(f"/notifications/{target['id']}/read", params={"recipient": PAYEE})
    assert response.status_code == 200
    assert response.json() == {**target, "read": True}
    assert _list(PAYEE)[0]["read"] is True
    assert all(n["read"] is False for n in _list(PAYER))


def test_mark_notification_read_is_idempotent():
    client.post("/transactions", json=SAMPLE_TX)
    target = _list(PAYEE)[0]
    url = f"/notifications/{target['id']}/read"
    client.post(url, params={"recipient": PAYEE})
    response = client.post(url, params={"recipient": PAYEE})
    assert response.status_code == 200
    assert response.json()["read"] is True


def test_mark_unknown_notification_is_404():
    response = client.post("/notifications/nope/read", params={"recipient": PAYEE})
    assert response.status_code == 404
    assert response.json() == {"detail": "Notification nope not found"}


def test_mark_other_recipients_notification_is_404():
    client.post("/transactions", json=SAMPLE_TX)
    target = _list(PAYEE)[0]
    response = client.post(f"/notifications/{target['id']}/read", params={"recipient": PAYER})
    assert response.status_code == 404
    assert _list(PAYEE)[0]["read"] is False


def test_mark_notification_read_requires_recipient():
    assert client.post("/notifications/nope/read").status_code == 422


def test_create_notification_defaults():
    n = notifications.create_notification(PAYER, NotificationType.TRANSACTION_FAILED, "Declined")
    assert n.transaction_id is None
    assert n.read is False
    assert n.created_at.tzinfo is not None
    assert notifications.list_notifications(PAYER) == [n]


def test_reset_store_clears_notifications():
    client.post("/transactions", json=SAMPLE_TX)
    reset_store()
    assert _list(PAYER) == []

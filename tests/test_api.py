import pytest
from fastapi.testclient import TestClient

from app.main import app, reset_store

client = TestClient(app)

SAMPLE_TX = {
    "from_account": "ES9121000418450200051332",
    "to_account": "GB29NWBK60161331926819",
    "amount": "125.50",
    "currency": "EUR",
    "reference": "Invoice 42",
}


@pytest.fixture(autouse=True)
def clean_store():
    reset_store()
    yield
    reset_store()


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "transactions": 0}


def test_create_transaction():
    response = client.post("/transactions", json=SAMPLE_TX)
    assert response.status_code == 201
    body = response.json()
    assert body["id"]
    assert body["status"] == "PENDING"
    assert body["amount"] == "125.50"
    assert body["currency"] == "EUR"
    assert body["reference"] == "Invoice 42"


def test_create_transaction_rejects_same_account():
    payload = {**SAMPLE_TX, "to_account": SAMPLE_TX["from_account"]}
    response = client.post("/transactions", json=payload)
    assert response.status_code == 422


def test_create_transaction_rejects_non_positive_amount():
    response = client.post("/transactions", json={**SAMPLE_TX, "amount": "0"})
    assert response.status_code == 422


def test_list_transactions():
    assert client.get("/transactions").json() == []

    client.post("/transactions", json=SAMPLE_TX)
    client.post("/transactions", json={**SAMPLE_TX, "amount": "10.00"})

    response = client.get("/transactions")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert [tx["amount"] for tx in body] == ["125.50", "10.00"]


def test_confirm_transaction():
    tx_id = client.post("/transactions", json=SAMPLE_TX).json()["id"]

    response = client.post(f"/transactions/{tx_id}/confirm")
    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"
    assert client.get(f"/transactions/{tx_id}").json()["status"] == "COMPLETED"


def test_confirm_transaction_rejects_non_pending():
    tx_id = client.post("/transactions", json=SAMPLE_TX).json()["id"]
    assert client.post(f"/transactions/{tx_id}/confirm").status_code == 200

    response = client.post(f"/transactions/{tx_id}/confirm")
    assert response.status_code == 409


def test_confirm_transaction_unknown_id():
    response = client.post("/transactions/does-not-exist/confirm")
    assert response.status_code == 404


def test_confirm_transaction_preserves_other_fields():
    created = client.post("/transactions", json=SAMPLE_TX).json()

    confirmed = client.post(f"/transactions/{created['id']}/confirm").json()
    assert confirmed == {**created, "status": "COMPLETED"}


def test_confirm_transaction_reflected_in_list_and_health():
    tx_id = client.post("/transactions", json=SAMPLE_TX).json()["id"]
    client.post("/transactions", json={**SAMPLE_TX, "amount": "10.00"})

    client.post(f"/transactions/{tx_id}/confirm")

    statuses = {tx["id"]: tx["status"] for tx in client.get("/transactions").json()}
    assert statuses[tx_id] == "COMPLETED"
    assert list(statuses.values()).count("PENDING") == 1
    assert client.get("/health").json() == {"status": "ok", "transactions": 2}


def test_confirm_transaction_error_details():
    tx_id = client.post("/transactions", json=SAMPLE_TX).json()["id"]
    client.post(f"/transactions/{tx_id}/confirm")

    conflict = client.post(f"/transactions/{tx_id}/confirm")
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == (
        f"Transaction {tx_id} is COMPLETED; only PENDING transactions can be confirmed"
    )

    missing = client.post("/transactions/does-not-exist/confirm")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Transaction does-not-exist not found"


def test_get_transaction_returns_pending_status():
    tx_id = client.post("/transactions", json=SAMPLE_TX).json()["id"]

    response = client.get(f"/transactions/{tx_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "PENDING"

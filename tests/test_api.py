import pytest
from fastapi.testclient import TestClient

from app.main import TransactionStatus, _transactions, app, reset_store

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
    assert body["status"] == "COMPLETED"
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


def test_refund_transaction():
    original = client.post("/transactions", json=SAMPLE_TX).json()

    response = client.post(f"/transactions/{original['id']}/refund")
    assert response.status_code == 201
    refund = response.json()
    assert refund["id"] != original["id"]
    assert refund["from_account"] == SAMPLE_TX["to_account"]
    assert refund["to_account"] == SAMPLE_TX["from_account"]
    assert refund["amount"] == "125.50"
    assert refund["currency"] == "EUR"
    assert refund["reference"] == f"Refund of {original['id']}"
    assert refund["status"] == "COMPLETED"

    assert client.get(f"/transactions/{original['id']}").json()["status"] == "REFUNDED"
    assert len(client.get("/transactions").json()) == 2


def test_refund_rejects_non_completed_transaction():
    original = client.post("/transactions", json=SAMPLE_TX).json()
    client.post(f"/transactions/{original['id']}/refund")

    # Original is now REFUNDED; refunding it again must be rejected.
    response = client.post(f"/transactions/{original['id']}/refund")
    assert response.status_code == 409
    assert len(_transactions) == 2


def test_refund_unknown_transaction():
    response = client.post("/transactions/does-not-exist/refund")
    assert response.status_code == 404


def test_refund_is_retrievable_and_ordered_after_original():
    original = client.post("/transactions", json=SAMPLE_TX).json()
    refund = client.post(f"/transactions/{original['id']}/refund").json()

    response = client.get(f"/transactions/{refund['id']}")
    assert response.status_code == 200
    assert response.json() == refund

    listed = client.get("/transactions").json()
    assert [tx["id"] for tx in listed] == [original["id"], refund["id"]]
    assert listed[0] == {**original, "status": "REFUNDED"}
    assert client.get("/health").json() == {"status": "ok", "transactions": 2}


def test_refund_rejects_pending_transaction():
    original = client.post("/transactions", json=SAMPLE_TX).json()
    _transactions[original["id"]] = _transactions[original["id"]].model_copy(
        update={"status": TransactionStatus.PENDING}
    )

    response = client.post(f"/transactions/{original['id']}/refund")
    assert response.status_code == 409
    assert response.json()["detail"] == f"Transaction {original['id']} is PENDING, not COMPLETED"
    assert len(_transactions) == 1
    assert client.get(f"/transactions/{original['id']}").json()["status"] == "PENDING"


def test_refund_already_refunded_detail_and_store_unchanged():
    original = client.post("/transactions", json=SAMPLE_TX).json()
    first = client.post(f"/transactions/{original['id']}/refund").json()

    response = client.post(f"/transactions/{original['id']}/refund")
    assert response.status_code == 409
    assert response.json()["detail"] == f"Transaction {original['id']} is REFUNDED, not COMPLETED"
    assert sorted(_transactions) == sorted([original["id"], first["id"]])


def test_refund_unknown_transaction_detail_and_store_unchanged():
    response = client.post("/transactions/does-not-exist/refund")
    assert response.status_code == 404
    assert response.json()["detail"] == "Transaction does-not-exist not found"
    assert client.get("/health").json() == {"status": "ok", "transactions": 0}


def test_refund_of_refund_is_allowed():
    original = client.post("/transactions", json=SAMPLE_TX).json()
    refund = client.post(f"/transactions/{original['id']}/refund").json()

    response = client.post(f"/transactions/{refund['id']}/refund")
    assert response.status_code == 201
    second = response.json()
    assert second["from_account"] == SAMPLE_TX["from_account"]
    assert second["to_account"] == SAMPLE_TX["to_account"]
    assert second["reference"] == f"Refund of {refund['id']}"
    assert client.get(f"/transactions/{refund['id']}").json()["status"] == "REFUNDED"
    assert len(_transactions) == 3

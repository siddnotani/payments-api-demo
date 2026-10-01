import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import reset_store

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_store():
    reset_store()
    yield
    reset_store()


def deposit(account, amount, currency="EUR"):
    return client.post(
        f"/accounts/{account}/deposits", json={"amount": amount, "currency": currency}
    )


def transfer(from_account, to_account, amount, currency="EUR"):
    return client.post(
        "/transactions",
        json={
            "from_account": from_account,
            "to_account": to_account,
            "amount": amount,
            "currency": currency,
        },
    )


def balances(account):
    response = client.get(f"/accounts/{account}/balance")
    assert response.status_code == 200
    return {b["currency"]: b["amount"] for b in response.json()["balances"]}


def test_deposit_credits_account_from_external():
    response = deposit("ACC-A", "100.00")
    assert response.status_code == 201
    body = response.json()
    assert body["from_account"] == "EXTERNAL"
    assert body["to_account"] == "ACC-A"
    assert body["status"] == "COMPLETED"
    assert client.get("/accounts/ACC-A/balance").json() == {
        "account": "ACC-A",
        "balances": [{"currency": "EUR", "amount": "100.00"}],
    }


def test_balance_accumulates_across_transactions():
    deposit("ACC-A", "100.00")
    deposit("ACC-A", "25.50")
    assert transfer("ACC-A", "ACC-B", "30.00").status_code == 201
    assert transfer("ACC-A", "ACC-B", "20.25").status_code == 201
    assert transfer("ACC-B", "ACC-C", "5.00").status_code == 201

    assert balances("ACC-A") == {"EUR": "75.25"}
    assert balances("ACC-B") == {"EUR": "45.25"}
    assert balances("ACC-C") == {"EUR": "5.00"}


def test_balances_are_tracked_per_currency():
    deposit("ACC-A", "100.00", "EUR")
    deposit("ACC-A", "50.00", "USD")
    transfer("ACC-A", "ACC-B", "10.00", "USD")

    response = client.get("/accounts/ACC-A/balance")
    assert response.json()["balances"] == [
        {"currency": "EUR", "amount": "100.00"},
        {"currency": "USD", "amount": "40.00"},
    ]
    assert balances("ACC-B") == {"USD": "10.00"}


def test_spending_entire_balance_is_allowed():
    deposit("ACC-A", "10.00")
    assert transfer("ACC-A", "ACC-B", "10.00").status_code == 201
    assert balances("ACC-A") == {"EUR": "0.00"}


def test_insufficient_funds_rejected_and_state_unchanged():
    deposit("ACC-A", "50.00")
    transfer("ACC-A", "ACC-B", "20.00")
    before = {
        "a": balances("ACC-A"),
        "b": balances("ACC-B"),
        "transactions": client.get("/transactions").json(),
        "health": client.get("/health").json(),
    }

    response = transfer("ACC-A", "ACC-B", "30.01")

    assert response.status_code == 422
    assert response.json() == {"detail": "Insufficient funds in ACC-A for EUR"}
    assert balances("ACC-A") == before["a"]
    assert balances("ACC-B") == before["b"]
    assert client.get("/transactions").json() == before["transactions"]
    assert client.get("/health").json() == before["health"]


def test_unfunded_sender_rejected_without_creating_accounts():
    response = transfer("ACC-A", "ACC-B", "1.00")
    assert response.status_code == 422
    assert client.get("/accounts/ACC-A/balance").status_code == 404
    assert client.get("/accounts/ACC-B/balance").status_code == 404
    assert client.get("/health").json() == {"status": "ok", "transactions": 0, "accounts": 0}


def test_insufficient_funds_is_per_currency():
    deposit("ACC-A", "100.00", "EUR")
    response = transfer("ACC-A", "ACC-B", "1.00", "GBP")
    assert response.status_code == 422
    assert response.json() == {"detail": "Insufficient funds in ACC-A for GBP"}


def test_unknown_account_balance_is_404():
    response = client.get("/accounts/ACC-UNKNOWN/balance")
    assert response.status_code == 404
    assert response.json() == {"detail": "Account ACC-UNKNOWN not found"}


@pytest.mark.parametrize("field", ["from_account", "to_account"])
def test_transfers_cannot_use_external_account(field):
    deposit("ACC-A", "100.00")
    accounts = {"from_account": "ACC-A", "to_account": "ACC-B", field: "EXTERNAL"}
    response = transfer(accounts["from_account"], accounts["to_account"], "1.00")
    assert response.status_code == 422
    assert "reserved" in response.json()["detail"]


def test_deposit_to_external_account_rejected():
    response = deposit("EXTERNAL", "1.00")
    assert response.status_code == 422
    assert client.get("/accounts/EXTERNAL/balance").status_code == 404


@pytest.mark.parametrize("amount", ["0", "-1.00"])
def test_deposit_rejects_non_positive_amount(amount):
    assert deposit("ACC-A", amount).status_code == 422
    assert client.get("/accounts/ACC-A/balance").status_code == 404


def test_health_counts_accounts_with_balances():
    deposit("ACC-A", "100.00")
    transfer("ACC-A", "ACC-B", "10.00")
    transfer("ACC-A", "ACC-C", "10.00")
    assert client.get("/health").json() == {"status": "ok", "transactions": 3, "accounts": 3}


def test_reset_store_clears_balances():
    deposit("ACC-A", "100.00")
    reset_store()
    assert client.get("/accounts/ACC-A/balance").status_code == 404
    assert client.get("/health").json()["accounts"] == 0

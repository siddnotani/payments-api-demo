from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import store
from app.main import app
from app.models import Currency, Transaction, TransactionStatus

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_store():
    store.reset_store()
    yield
    store.reset_store()


def deposit(account, amount, currency="EUR", reference=None):
    response = client.post(
        f"/accounts/{account}/deposits",
        json={"amount": amount, "currency": currency, "reference": reference},
    )
    assert response.status_code == 201
    return response.json()


def transfer(from_account, to_account, amount, currency="EUR", reference=None):
    response = client.post(
        "/transactions",
        json={
            "from_account": from_account,
            "to_account": to_account,
            "amount": amount,
            "currency": currency,
            "reference": reference,
        },
    )
    assert response.status_code == 201
    return response.json()


def seed(from_account, to_account, amount, created_at):
    """Insert a transaction with a fixed timestamp directly into the store."""
    tx = Transaction(
        id=str(uuid4()),
        status=TransactionStatus.COMPLETED,
        created_at=created_at,
        from_account=from_account,
        to_account=to_account,
        amount=Decimal(amount),
        currency=Currency.EUR,
    )
    store.add_transaction(tx)
    return tx


def statement(account, **params):
    response = client.get(f"/accounts/{account}/statement", params=params)
    assert response.status_code == 200
    return response.json()


def test_unknown_account_statement_is_404():
    response = client.get("/accounts/ACC-UNKNOWN/statement")
    assert response.status_code == 404
    assert response.json() == {"detail": "Account ACC-UNKNOWN not found"}


def test_statement_entry_shape():
    dep = deposit("ACC-A", "100.00", reference="Opening balance")
    body = statement("ACC-A")

    assert body["account"] == "ACC-A"
    generated_at = datetime.fromisoformat(body["generated_at"])
    assert generated_at.tzinfo is not None
    assert body["entries"] == [
        {
            "transaction_id": dep["id"],
            "direction": "CREDIT",
            "counterparty": "EXTERNAL",
            "amount": "100.00",
            "currency": "EUR",
            "reference": "Opening balance",
            "timestamp": dep["created_at"],
            "running_balance": "100.00",
        }
    ]


def test_directions_and_counterparties_from_each_side():
    deposit("ACC-A", "100.00")
    tx = transfer("ACC-A", "ACC-B", "40.00", reference="Rent")

    a_entry = statement("ACC-A")["entries"][-1]
    b_entry = statement("ACC-B")["entries"][-1]

    assert a_entry["transaction_id"] == b_entry["transaction_id"] == tx["id"]
    assert (a_entry["direction"], a_entry["counterparty"]) == ("DEBIT", "ACC-B")
    assert (b_entry["direction"], b_entry["counterparty"]) == ("CREDIT", "ACC-A")
    assert a_entry["reference"] == b_entry["reference"] == "Rent"


def test_running_balance_matches_each_step_and_final_balance():
    deposit("ACC-A", "100.00")
    deposit("ACC-B", "50.00")
    transfer("ACC-A", "ACC-B", "30.00")
    transfer("ACC-B", "ACC-A", "10.00")
    transfer("ACC-A", "ACC-C", "5.25")

    entries = statement("ACC-A")["entries"]

    assert [(e["direction"], e["amount"], e["running_balance"]) for e in entries] == [
        ("CREDIT", "100.00", "100.00"),
        ("DEBIT", "30.00", "70.00"),
        ("CREDIT", "10.00", "80.00"),
        ("DEBIT", "5.25", "74.75"),
    ]
    balance = client.get("/accounts/ACC-A/balance").json()["balances"]
    assert balance == [{"currency": "EUR", "amount": entries[-1]["running_balance"]}]


def test_running_balance_is_tracked_per_currency():
    deposit("ACC-A", "100.00", "EUR")
    deposit("ACC-A", "20.00", "USD")
    transfer("ACC-A", "ACC-B", "15.00", "EUR")
    transfer("ACC-A", "ACC-B", "5.00", "USD")

    entries = statement("ACC-A")["entries"]

    assert [(e["currency"], e["running_balance"]) for e in entries] == [
        ("EUR", "100.00"),
        ("USD", "20.00"),
        ("EUR", "85.00"),
        ("USD", "15.00"),
    ]


def test_entries_ordered_by_created_at_not_insertion():
    seed("EXTERNAL", "ACC-A", "100.00", datetime(2026, 9, 1, tzinfo=UTC))
    later = seed("ACC-A", "ACC-B", "10.00", datetime(2026, 9, 20, tzinfo=UTC))
    earlier = seed("ACC-A", "ACC-C", "20.00", datetime(2026, 9, 10, tzinfo=UTC))

    entries = statement("ACC-A")["entries"]
    timestamps = [e["timestamp"] for e in entries]

    assert timestamps == sorted(timestamps)
    assert [e["transaction_id"] for e in entries][1:] == [earlier.id, later.id]
    assert [e["running_balance"] for e in entries] == ["100.00", "80.00", "70.00"]


@pytest.fixture
def september_history():
    return [
        seed("EXTERNAL", "ACC-A", "100.00", datetime(2026, 9, 1, 9, tzinfo=UTC)),
        seed("ACC-A", "ACC-B", "10.00", datetime(2026, 9, 10, 0, 0, tzinfo=UTC)),
        seed("ACC-A", "ACC-B", "20.00", datetime(2026, 9, 15, 12, tzinfo=UTC)),
        seed("ACC-A", "ACC-B", "30.00", datetime(2026, 9, 20, 23, 59, tzinfo=UTC)),
    ]


def ids(body):
    return [e["transaction_id"] for e in body["entries"]]


def test_from_date_filter_is_inclusive_and_keeps_historical_running_balance(
    september_history,
):
    body = statement("ACC-A", from_date="2026-09-10")
    assert ids(body) == [t.id for t in september_history[1:]]
    assert [e["running_balance"] for e in body["entries"]] == ["90.00", "70.00", "40.00"]


def test_to_date_filter_is_inclusive(september_history):
    body = statement("ACC-A", to_date="2026-09-20")
    assert ids(body) == [t.id for t in september_history]
    body = statement("ACC-A", to_date="2026-09-15")
    assert ids(body) == [t.id for t in september_history[:3]]


def test_from_and_to_date_filter(september_history):
    body = statement("ACC-A", from_date="2026-09-11", to_date="2026-09-19")
    assert ids(body) == [september_history[2].id]
    assert body["entries"][0]["running_balance"] == "70.00"


def test_date_range_without_entries_returns_empty_statement(september_history):
    body = statement("ACC-A", from_date="2026-10-01")
    assert body["account"] == "ACC-A"
    assert body["entries"] == []


def test_from_date_after_to_date_is_422(september_history):
    response = client.get(
        "/accounts/ACC-A/statement", params={"from_date": "2026-09-20", "to_date": "2026-09-01"}
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "from_date must be on or before to_date"}


def test_invalid_date_is_422(september_history):
    response = client.get("/accounts/ACC-A/statement", params={"from_date": "not-a-date"})
    assert response.status_code == 422


def test_rejected_transfer_not_on_statement():
    deposit("ACC-A", "10.00")
    response = client.post(
        "/transactions",
        json={"from_account": "ACC-A", "to_account": "ACC-B", "amount": "50.00"},
    )
    assert response.status_code == 422
    assert len(statement("ACC-A")["entries"]) == 1
    assert client.get("/accounts/ACC-B/statement").status_code == 404

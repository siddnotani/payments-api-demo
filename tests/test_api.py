from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import Transaction, TransactionStatus, _transactions, app, reset_store
from app.scheduler import JobResult, job

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


def test_list_jobs_includes_heartbeat():
    names = [j["name"] for j in client.get("/ops/jobs").json()]
    assert "heartbeat" in names


def test_run_job_dry_run():
    response = client.post("/ops/jobs/heartbeat/run")
    assert response.status_code == 200
    assert response.json()["job"] == "heartbeat"


def test_run_unknown_job_is_404():
    assert client.post("/ops/jobs/nope/run").status_code == 404


def test_simulated_incident_returns_500():
    response = client.post("/ops/incidents/fx_timeout")
    assert response.status_code == 500
    assert "timed out" in response.json()["error"]


def test_list_jobs_returns_job_metadata():
    response = client.get("/ops/jobs")
    assert response.status_code == 200
    heartbeat = next(j for j in response.json() if j["name"] == "heartbeat")
    assert heartbeat == {
        "name": "heartbeat",
        "schedule": "*/5 * * * *",
        "description": "Proves the scheduler is alive.",
    }


def test_run_job_returns_result_payload():
    response = client.post("/ops/jobs/heartbeat/run")
    assert response.status_code == 200
    body = response.json()
    assert body["processed"] == 0
    assert len(body["notes"]) == 1
    assert body["notes"][0].startswith("alive at ")


def test_run_job_with_dry_run_false():
    response = client.post("/ops/jobs/heartbeat/run", params={"dry_run": "false"})
    assert response.status_code == 200
    assert response.json()["job"] == "heartbeat"


def test_run_job_rejects_invalid_dry_run():
    response = client.post("/ops/jobs/heartbeat/run", params={"dry_run": "maybe"})
    assert response.status_code == 422


def test_run_unknown_job_404_detail():
    response = client.post("/ops/jobs/nope/run")
    assert response.json() == {"detail": "Job nope not found"}


def test_register_duplicate_job_name_raises():
    with pytest.raises(ValueError, match="already registered"):
        job("heartbeat", schedule="* * * * *")(lambda ctx: JobResult())


@pytest.mark.parametrize(
    ("scenario", "fragment"),
    [
        ("fx_timeout", "timed out"),
        ("ledger_drift", "drift"),
        ("duplicate_settlement", "already exported"),
    ],
)
def test_simulated_incident_all_scenarios(scenario, fragment):
    response = client.post(f"/ops/incidents/{scenario}")
    assert response.status_code == 500
    body = response.json()
    assert body["scenario"] == scenario
    assert fragment in body["error"]


def test_simulated_incident_rejects_unknown_scenario():
    response = client.post("/ops/incidents/meteor_strike")
    assert response.status_code == 422


def test_analytics_summary_empty_store():
    response = client.get("/analytics/summary")
    assert response.status_code == 200
    assert response.json() == {
        "total_transactions": 0,
        "total_volume_by_currency": [
            {"currency": "EUR", "count": 0, "total_amount": "0"},
            {"currency": "GBP", "count": 0, "total_amount": "0"},
            {"currency": "USD", "count": 0, "total_amount": "0"},
        ],
        "by_status": {"PENDING": 0, "COMPLETED": 0},
        "largest_transaction": None,
    }


def test_analytics_summary_aggregates_currencies_and_statuses():
    client.post("/transactions", json=SAMPLE_TX)
    client.post("/transactions", json={**SAMPLE_TX, "amount": "10.00"})
    largest = client.post(
        "/transactions", json={**SAMPLE_TX, "amount": "999.99", "currency": "USD"}
    ).json()
    pending = Transaction(
        id="pending-1",
        status=TransactionStatus.PENDING,
        created_at=datetime.now(UTC),
        **{**SAMPLE_TX, "amount": Decimal("5.25"), "currency": "GBP"},
    )
    _transactions[pending.id] = pending

    response = client.get("/analytics/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["total_transactions"] == 4
    assert body["total_volume_by_currency"] == [
        {"currency": "EUR", "count": 2, "total_amount": "135.50"},
        {"currency": "GBP", "count": 1, "total_amount": "5.25"},
        {"currency": "USD", "count": 1, "total_amount": "999.99"},
    ]
    assert body["by_status"] == {"PENDING": 1, "COMPLETED": 3}
    assert body["largest_transaction"] == largest


def test_analytics_summary_total_is_exact_for_large_amounts():
    big = "1" + "0" * 40 + ".01"
    client.post("/transactions", json={**SAMPLE_TX, "amount": big})
    client.post("/transactions", json={**SAMPLE_TX, "amount": "0.01"})

    eur = client.get("/analytics/summary").json()["total_volume_by_currency"][0]
    assert eur == {"currency": "EUR", "count": 2, "total_amount": "1" + "0" * 40 + ".02"}


@pytest.mark.parametrize("currency", ["EUR", "GBP", "USD"])
@pytest.mark.parametrize("status", [TransactionStatus.PENDING, TransactionStatus.COMPLETED])
def test_analytics_summary_single_transaction_keeps_zero_buckets(currency, status):
    transaction = Transaction(
        id="single-transaction",
        status=status,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        **{**SAMPLE_TX, "currency": currency},
    )
    _transactions[transaction.id] = transaction

    response = client.get("/analytics/summary")
    assert response.status_code == 200
    assert response.json() == {
        "total_transactions": 1,
        "total_volume_by_currency": [
            {
                "currency": bucket,
                "count": int(bucket == currency),
                "total_amount": "125.50" if bucket == currency else "0",
            }
            for bucket in ["EUR", "GBP", "USD"]
        ],
        "by_status": {
            "PENDING": int(status == TransactionStatus.PENDING),
            "COMPLETED": int(status == TransactionStatus.COMPLETED),
        },
        "largest_transaction": transaction.model_dump(mode="json"),
    }


def test_analytics_summary_largest_tie_uses_earliest_created_at():
    later = Transaction(
        id="later-largest",
        status=TransactionStatus.COMPLETED,
        created_at=datetime(2026, 1, 3, tzinfo=UTC),
        **{**SAMPLE_TX, "amount": "999.99", "currency": "USD"},
    )
    earlier = Transaction(
        id="earlier-largest",
        status=TransactionStatus.PENDING,
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        **{**SAMPLE_TX, "amount": "999.99", "currency": "GBP"},
    )
    smallest = Transaction(
        id="earliest-but-smaller",
        status=TransactionStatus.COMPLETED,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        **SAMPLE_TX,
    )
    for transaction in [later, earlier, smallest]:
        _transactions[transaction.id] = transaction

    response = client.get("/analytics/summary")
    assert response.status_code == 200
    assert response.json()["largest_transaction"] == earlier.model_dump(mode="json")


@pytest.mark.parametrize("currency", ["EUR", "GBP", "USD"])
def test_analytics_summary_preserves_fractional_precision(currency):
    for amount in ["0.10", "0.20", "0.0001"]:
        response = client.post(
            "/transactions", json={**SAMPLE_TX, "amount": amount, "currency": currency}
        )
        assert response.status_code == 201

    response = client.get("/analytics/summary")
    assert response.status_code == 200
    bucket = next(
        item for item in response.json()["total_volume_by_currency"] if item["currency"] == currency
    )
    assert bucket == {"currency": currency, "count": 3, "total_amount": "0.3001"}


def test_analytics_summary_reflects_new_transactions_without_mutating_store():
    created = client.post("/transactions", json=SAMPLE_TX)
    assert created.status_code == 201
    transactions_before = client.get("/transactions").json()

    first = client.get("/analytics/summary")
    repeated = client.get("/analytics/summary")
    assert first.status_code == repeated.status_code == 200
    assert first.json() == repeated.json()
    assert first.json()["total_transactions"] == 1
    assert client.get("/transactions").json() == transactions_before

    created = client.post("/transactions", json={**SAMPLE_TX, "amount": "200.00"})
    assert created.status_code == 201
    transactions_after = client.get("/transactions").json()

    updated = client.get("/analytics/summary")
    assert updated.status_code == 200
    assert updated.json()["total_transactions"] == 2
    assert updated.json()["total_volume_by_currency"][0] == {
        "currency": "EUR",
        "count": 2,
        "total_amount": "325.50",
    }
    assert updated.json()["by_status"] == {"PENDING": 0, "COMPLETED": 2}
    assert updated.json()["largest_transaction"] == created.json()
    assert client.get("/transactions").json() == transactions_after

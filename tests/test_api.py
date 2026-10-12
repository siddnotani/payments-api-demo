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


def test_analytics_empty_store():
    response = client.get("/analytics")
    assert response.status_code == 200
    assert response.json() == {
        "total_transactions": 0,
        "by_currency": [],
        "by_status": {"PENDING": 0, "COMPLETED": 0},
    }


def test_analytics_groups_by_currency_and_status():
    client.post("/transactions", json=SAMPLE_TX)
    client.post("/transactions", json={**SAMPLE_TX, "amount": "10.25"})
    client.post("/transactions", json={**SAMPLE_TX, "amount": "99.99", "currency": "GBP"})
    client.post("/transactions", json={**SAMPLE_TX, "amount": "0.01", "currency": "USD"})
    pending = Transaction(
        id="pending-1",
        status=TransactionStatus.PENDING,
        created_at=datetime.now(UTC),
        **{**SAMPLE_TX, "amount": Decimal("5.00"), "currency": "USD"},
    )
    _transactions[pending.id] = pending

    response = client.get("/analytics")
    assert response.status_code == 200
    body = response.json()
    assert body["total_transactions"] == 5
    assert body["by_currency"] == [
        {"currency": "EUR", "count": 2, "total_amount": "135.75"},
        {"currency": "GBP", "count": 1, "total_amount": "99.99"},
        {"currency": "USD", "count": 2, "total_amount": "5.01"},
    ]
    assert body["by_status"] == {"PENDING": 1, "COMPLETED": 4}


def test_analytics_sums_large_amounts_exactly():
    big = "12345678901234567890123456789.01"
    client.post("/transactions", json={**SAMPLE_TX, "amount": big})
    client.post("/transactions", json={**SAMPLE_TX, "amount": "0.01"})

    eur = client.get("/analytics").json()["by_currency"][0]
    assert eur == {
        "currency": "EUR",
        "count": 2,
        "total_amount": "12345678901234567890123456789.02",
    }


def test_analytics_omits_unused_currencies_and_zero_fills_statuses():
    client.post("/transactions", json={**SAMPLE_TX, "amount": "7.25", "currency": "GBP"})

    response = client.get("/analytics")
    assert response.status_code == 200
    assert response.json() == {
        "total_transactions": 1,
        "by_currency": [{"currency": "GBP", "count": 1, "total_amount": "7.25"}],
        "by_status": {"PENDING": 0, "COMPLETED": 1},
    }


def test_analytics_ignores_rejected_transactions():
    client.post("/transactions", json=SAMPLE_TX)
    assert client.post("/transactions", json={**SAMPLE_TX, "amount": "0"}).status_code == 422
    same_account = {**SAMPLE_TX, "to_account": SAMPLE_TX["from_account"]}
    assert client.post("/transactions", json=same_account).status_code == 422

    body = client.get("/analytics").json()
    assert body["total_transactions"] == 1
    assert body["by_currency"] == [{"currency": "EUR", "count": 1, "total_amount": "125.50"}]
    assert body["by_status"] == {"PENDING": 0, "COMPLETED": 1}


def test_analytics_sums_mixed_scale_amounts():
    client.post("/transactions", json={**SAMPLE_TX, "amount": "10"})
    client.post("/transactions", json={**SAMPLE_TX, "amount": "0.5"})

    eur = client.get("/analytics").json()["by_currency"][0]
    assert eur["total_amount"] == "10.5"


def test_analytics_sums_tiny_amounts_below_default_exponent_range():
    tiny = "1E-1000030"
    client.post("/transactions", json={**SAMPLE_TX, "amount": tiny})
    client.post("/transactions", json={**SAMPLE_TX, "amount": tiny})

    eur = client.get("/analytics").json()["by_currency"][0]
    assert Decimal(eur["total_amount"]) == Decimal("2E-1000030")

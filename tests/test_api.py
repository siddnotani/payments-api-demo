from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import Transaction, TransactionStatus, app, compute_analytics, reset_store
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
    response = client.get("/analytics/summary")
    assert response.status_code == 200
    assert response.json() == {
        "total_transactions": 0,
        "by_currency": [],
        "by_status": {"PENDING": 0, "COMPLETED": 0},
        "first_transaction_at": None,
        "last_transaction_at": None,
        "largest_transaction": None,
    }


def test_analytics_summary_aggregates_by_currency():
    for currency, amount in [
        ("EUR", "10.00"),
        ("EUR", "20.00"),
        ("EUR", "0.10"),
        ("USD", "100.00"),
        ("GBP", "5.25"),
    ]:
        client.post("/transactions", json={**SAMPLE_TX, "currency": currency, "amount": amount})

    response = client.get("/analytics/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["total_transactions"] == 5
    assert body["by_status"] == {"PENDING": 0, "COMPLETED": 5}
    assert [c["currency"] for c in body["by_currency"]] == ["USD", "EUR", "GBP"]

    eur = next(c for c in body["by_currency"] if c["currency"] == "EUR")
    assert eur["count"] == 3
    assert eur["total_amount"] == "30.10"
    assert eur["average_amount"] == "10.03"
    assert eur["min_amount"] == "0.10"
    assert eur["max_amount"] == "20.00"

    usd = next(c for c in body["by_currency"] if c["currency"] == "USD")
    assert usd["count"] == 1
    assert usd["total_amount"] == "100.00"
    assert usd["average_amount"] == "100.00"

    assert body["first_transaction_at"] <= body["last_transaction_at"]


def test_analytics_largest_transaction():
    ids = {}
    for amount in ["125.50", "999.99", "42.00"]:
        ids[amount] = client.post("/transactions", json={**SAMPLE_TX, "amount": amount}).json()[
            "id"
        ]

    body = client.get("/analytics/summary").json()
    assert body["largest_transaction"]["id"] == ids["999.99"]
    assert body["largest_transaction"]["amount"] == "999.99"


def test_analytics_average_rounds_half_even():
    for amount in ["0.01", "0.04"]:
        client.post("/transactions", json={**SAMPLE_TX, "amount": amount})

    eur = client.get("/analytics/summary").json()["by_currency"][0]
    assert eur["total_amount"] == "0.05"
    assert eur["average_amount"] == "0.02"


def test_analytics_total_amount_is_exact_decimal():
    for _ in range(3):
        client.post("/transactions", json={**SAMPLE_TX, "amount": "0.10"})

    eur = client.get("/analytics/summary").json()["by_currency"][0]
    assert eur["total_amount"] == "0.30"
    assert eur["average_amount"] == "0.10"


def test_analytics_only_lists_currencies_with_transactions():
    client.post("/transactions", json={**SAMPLE_TX, "currency": "GBP", "amount": "7.00"})

    body = client.get("/analytics/summary").json()
    assert body["by_currency"] == [
        {
            "currency": "GBP",
            "count": 1,
            "total_amount": "7.00",
            "average_amount": "7.00",
            "min_amount": "7.00",
            "max_amount": "7.00",
        }
    ]


def test_analytics_first_and_last_transaction_timestamps():
    created = [
        client.post("/transactions", json={**SAMPLE_TX, "amount": amount}).json()
        for amount in ["1.00", "2.00", "3.00"]
    ]

    body = client.get("/analytics/summary").json()
    assert body["first_transaction_at"] == created[0]["created_at"]
    assert body["last_transaction_at"] == created[-1]["created_at"]


def test_analytics_summary_rejects_post():
    assert client.post("/analytics/summary").status_code == 405


def test_compute_analytics_counts_pending_status():
    def make_tx(tx_status):
        return Transaction(
            **SAMPLE_TX,
            id=str(tx_status),
            status=tx_status,
            created_at=datetime.now(UTC),
        )

    summary = compute_analytics(
        [
            make_tx(TransactionStatus.PENDING),
            make_tx(TransactionStatus.PENDING),
            make_tx(TransactionStatus.COMPLETED),
        ]
    )
    assert summary.by_status == {"PENDING": 2, "COMPLETED": 1}
    assert summary.by_currency[0].total_amount == Decimal("376.50")


def test_analytics_handles_very_large_amount():
    unsafe_client = TestClient(app, raise_server_exceptions=False)
    huge = "1000000000000000000000000000"
    created = unsafe_client.post("/transactions", json={**SAMPLE_TX, "amount": huge})
    assert created.status_code == 201

    response = unsafe_client.get("/analytics/summary")
    assert response.status_code == 200
    eur = response.json()["by_currency"][0]
    assert eur["total_amount"] == huge
    assert eur["average_amount"] == huge + ".00"


def test_analytics_total_stays_exact_beyond_default_precision():
    amounts = ["1000000000000000000000000000.01", "0.02"]
    for amount in amounts:
        client.post("/transactions", json={**SAMPLE_TX, "amount": amount})

    eur = client.get("/analytics/summary").json()["by_currency"][0]
    assert eur["total_amount"] == "1000000000000000000000000000.03"
    assert eur["average_amount"] == "500000000000000000000000000.02"

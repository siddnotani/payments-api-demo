from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.main import Transaction, TransactionStatus, app, reset_store
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
        "total_amount_by_currency": {},
        "count_by_currency": {},
        "count_by_status": {},
        "average_amount": None,
        "largest_transaction": None,
    }


def test_analytics_summary_aggregates_transactions():
    client.post("/transactions", json=SAMPLE_TX)
    client.post("/transactions", json={**SAMPLE_TX, "amount": "10.00"})
    largest = client.post(
        "/transactions", json={**SAMPLE_TX, "amount": "300.25", "currency": "USD"}
    ).json()
    client.post("/transactions", json={**SAMPLE_TX, "amount": "5", "currency": "GBP"})

    response = client.get("/analytics/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["total_transactions"] == 4
    assert body["total_amount_by_currency"] == {"EUR": "135.50", "USD": "300.25", "GBP": "5"}
    assert body["count_by_currency"] == {"EUR": 2, "USD": 1, "GBP": 1}
    assert body["count_by_status"] == {"COMPLETED": 4}
    assert body["average_amount"] == "110.19"
    assert body["largest_transaction"] == largest


def test_analytics_summary_counts_pending_status():
    client.post("/transactions", json=SAMPLE_TX)
    pending = Transaction(
        id="pending-1",
        status=TransactionStatus.PENDING,
        created_at=datetime.now(UTC),
        **{**SAMPLE_TX, "amount": "1.00"},
    )
    main._transactions[pending.id] = pending

    body = client.get("/analytics/summary").json()
    assert body["count_by_status"] == {"COMPLETED": 1, "PENDING": 1}
    assert body["total_amount_by_currency"] == {"EUR": "126.50"}


def test_analytics_summary_large_amounts_are_exact():
    big = "123456789012345678901234567890.01"
    client.post("/transactions", json={**SAMPLE_TX, "amount": big})
    client.post("/transactions", json={**SAMPLE_TX, "amount": big})

    body = client.get("/analytics/summary").json()
    assert body["total_amount_by_currency"] == {"EUR": "246913578024691357802469135780.02"}
    assert body["average_amount"] == big


@pytest.mark.parametrize(
    ("amount", "expected_average"),
    [("0.125", "0.12"), ("0.135", "0.14"), ("5", "5.00")],
)
def test_analytics_summary_average_rounds_half_even_to_2dp(amount, expected_average):
    client.post("/transactions", json={**SAMPLE_TX, "amount": amount})

    body = client.get("/analytics/summary").json()
    assert body["average_amount"] == expected_average


def test_analytics_summary_totals_keep_sub_cent_precision():
    client.post("/transactions", json={**SAMPLE_TX, "amount": "0.001"})
    client.post("/transactions", json={**SAMPLE_TX, "amount": "0.002"})

    body = client.get("/analytics/summary").json()
    assert body["total_amount_by_currency"] == {"EUR": "0.003"}
    assert body["average_amount"] == "0.00"


def test_analytics_summary_excludes_rejected_transactions():
    client.post("/transactions", json=SAMPLE_TX)
    rejected = client.post("/transactions", json={**SAMPLE_TX, "amount": "0"})
    assert rejected.status_code == 422

    body = client.get("/analytics/summary").json()
    assert body["total_transactions"] == 1
    assert body["total_amount_by_currency"] == {"EUR": "125.50"}


def test_analytics_summary_largest_tie_returns_first_created():
    first = client.post("/transactions", json={**SAMPLE_TX, "amount": "50"}).json()
    client.post("/transactions", json={**SAMPLE_TX, "amount": "50.00", "currency": "USD"})

    body = client.get("/analytics/summary").json()
    assert body["largest_transaction"]["id"] == first["id"]


def test_analytics_summary_rejects_post():
    assert client.post("/analytics/summary").status_code == 405

import pytest
from fastapi.testclient import TestClient

from app.main import app, reset_store
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


EMPTY_SUMMARY = {
    "total_transactions": 0,
    "total_volume": {},
    "average_amount": {},
    "max_amount": None,
    "min_amount": None,
    "by_status": {"PENDING": 0, "COMPLETED": 0},
}


def test_analytics_summary_empty_store():
    response = client.get("/analytics/summary")
    assert response.status_code == 200
    assert response.json() == EMPTY_SUMMARY


def test_analytics_summary_seeded_transactions():
    for amount, currency in [
        ("125.50", "EUR"),
        ("10.00", "EUR"),
        ("0.01", "EUR"),
        ("99.99", "USD"),
        ("300", "GBP"),
        ("200.25", "GBP"),
    ]:
        client.post("/transactions", json={**SAMPLE_TX, "amount": amount, "currency": currency})

    response = client.get("/analytics/summary")
    assert response.status_code == 200
    assert response.json() == {
        "total_transactions": 6,
        "total_volume": {"EUR": "135.51", "USD": "99.99", "GBP": "500.25"},
        "average_amount": {"EUR": "45.17", "USD": "99.99", "GBP": "250.12"},
        "max_amount": "300",
        "min_amount": "0.01",
        "by_status": {"PENDING": 0, "COMPLETED": 6},
    }


def test_analytics_summary_updates_after_new_transaction():
    client.post("/transactions", json=SAMPLE_TX)
    before = client.get("/analytics/summary").json()
    assert before["total_transactions"] == 1
    assert before["total_volume"] == {"EUR": "125.50"}

    client.post("/transactions", json={**SAMPLE_TX, "amount": "4.50"})
    client.post("/transactions", json={**SAMPLE_TX, "amount": "7.25", "currency": "USD"})

    after = client.get("/analytics/summary").json()
    assert after["total_transactions"] == 3
    assert after["total_volume"] == {"EUR": "130.00", "USD": "7.25"}
    assert after["average_amount"] == {"EUR": "65.00", "USD": "7.25"}
    assert after["max_amount"] == "125.50"
    assert after["min_amount"] == "4.50"
    assert after["by_status"]["COMPLETED"] == 3


def test_analytics_summary_exact_for_large_amounts():
    big = "1" + "0" * 40
    client.post("/transactions", json={**SAMPLE_TX, "amount": big})
    client.post("/transactions", json={**SAMPLE_TX, "amount": "0.01"})

    body = client.get("/analytics/summary").json()
    assert body["total_volume"]["EUR"] == big + ".01"
    assert body["average_amount"]["EUR"] == "5" + "0" * 39 + ".00"
    assert body["max_amount"] == big

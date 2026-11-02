from datetime import UTC, datetime

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


def test_analytics_summary_empty_store():
    response = client.get("/analytics/summary")
    assert response.status_code == 200
    assert response.json() == {
        "total_transactions": 0,
        "by_currency": [],
        "first_transaction_at": None,
        "last_transaction_at": None,
    }


def test_analytics_summary_groups_by_currency():
    first = client.post("/transactions", json=SAMPLE_TX).json()
    client.post("/transactions", json={**SAMPLE_TX, "amount": "10.00"})
    last = client.post("/transactions", json={**SAMPLE_TX, "amount": "50.00", "currency": "USD"})
    last = last.json()

    response = client.get("/analytics/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["total_transactions"] == 3
    assert body["by_currency"] == [
        {"currency": "EUR", "count": 2, "total_amount": "135.50", "average_amount": "67.75"},
        {"currency": "USD", "count": 1, "total_amount": "50.00", "average_amount": "50.00"},
    ]
    assert body["first_transaction_at"] == first["created_at"]
    assert body["last_transaction_at"] == last["created_at"]


def test_analytics_summary_average_rounds_half_up():
    for amount in ("10.00", "10.00", "10.01"):
        client.post("/transactions", json={**SAMPLE_TX, "amount": amount})

    (eur,) = client.get("/analytics/summary").json()["by_currency"]
    assert eur["total_amount"] == "30.01"
    assert eur["average_amount"] == "10.00"


def test_analytics_summary_large_amounts_stay_exact():
    client.post("/transactions", json={**SAMPLE_TX, "amount": "1E+40"})
    client.post("/transactions", json={**SAMPLE_TX, "amount": "0.01"})

    (eur,) = client.get("/analytics/summary").json()["by_currency"]
    assert eur["total_amount"] == "1" + "0" * 40 + ".01"
    assert eur["average_amount"] == "5" + "0" * 39 + ".01"


def test_analytics_summary_sorts_currencies_by_code():
    for currency in ("USD", "GBP", "EUR"):
        client.post("/transactions", json={**SAMPLE_TX, "currency": currency})

    body = client.get("/analytics/summary").json()
    assert body["total_transactions"] == 3
    assert [c["currency"] for c in body["by_currency"]] == ["EUR", "GBP", "USD"]
    assert all(c["count"] == 1 for c in body["by_currency"])


@pytest.mark.parametrize(
    ("amounts", "expected_average"),
    [
        (("0.01", "0.04"), "0.03"),
        (("0.01", "0.02"), "0.02"),
        (("0.005",), "0.01"),
        (("0.004",), "0.00"),
    ],
)
def test_analytics_summary_average_rounds_half_up_at_midpoint(amounts, expected_average):
    for amount in amounts:
        client.post("/transactions", json={**SAMPLE_TX, "amount": amount})

    (eur,) = client.get("/analytics/summary").json()["by_currency"]
    assert eur["count"] == len(amounts)
    assert eur["average_amount"] == expected_average


def test_analytics_summary_timestamps_are_min_and_max_created_at(monkeypatch):
    import app.main as main

    stamps = iter(
        [
            datetime(2026, 1, 3, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, tzinfo=UTC),
        ]
    )

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(stamps)

    monkeypatch.setattr(main, "datetime", FakeDatetime)
    for _ in range(3):
        client.post("/transactions", json=SAMPLE_TX)

    body = client.get("/analytics/summary").json()
    assert body["first_transaction_at"] == "2026-01-01T00:00:00Z"
    assert body["last_transaction_at"] == "2026-01-03T00:00:00Z"


def test_analytics_summary_rejects_post():
    assert client.post("/analytics/summary").status_code == 405

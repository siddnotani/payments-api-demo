from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import app.main as main
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


def _create(amount: str, currency: str = "EUR", created_at: datetime | None = None) -> dict:
    response = client.post(
        "/transactions", json={**SAMPLE_TX, "amount": amount, "currency": currency}
    )
    assert response.status_code == 201
    body = response.json()
    if created_at is not None:
        main._transactions[body["id"]].created_at = created_at
    return body


def _summary(**params) -> dict:
    response = client.get("/analytics/summary", params=params)
    assert response.status_code == 200
    return response.json()


def test_analytics_summary_empty_store():
    assert _summary() == {
        "total_transactions": 0,
        "per_currency": [],
        "status_counts": {"PENDING": 0, "COMPLETED": 0},
    }


def test_analytics_summary_aggregates_per_currency_and_status():
    for amount in ("10.00", "20.50", "0.01"):
        _create(amount, "EUR")
    for amount in ("100", "200"):
        _create(amount, "GBP")
    _create("7.25", "USD")
    tx = _create("5.00", "USD")
    main._transactions[tx["id"]].status = main.TransactionStatus.PENDING

    body = _summary()

    assert body["total_transactions"] == 7
    assert body["status_counts"] == {"PENDING": 1, "COMPLETED": 6}
    assert body["per_currency"] == [
        {
            "currency": "EUR",
            "count": 3,
            "total_amount": "30.51",
            "min_amount": "0.01",
            "max_amount": "20.50",
            "avg_amount": "10.17",
        },
        {
            "currency": "GBP",
            "count": 2,
            "total_amount": "300",
            "min_amount": "100",
            "max_amount": "200",
            "avg_amount": "150.00",
        },
        {
            "currency": "USD",
            "count": 2,
            "total_amount": "12.25",
            "min_amount": "5.00",
            "max_amount": "7.25",
            "avg_amount": "6.13",
        },
    ]


def test_analytics_summary_average_rounds_half_up():
    _create("0.01")
    _create("0.02")
    assert _summary()["per_currency"][0]["avg_amount"] == "0.02"


def test_analytics_summary_is_exact_for_large_amounts():
    big = "99999999999999999999999999999.99"
    for _ in range(3):
        _create(big)
    stats = _summary()["per_currency"][0]
    assert stats["total_amount"] == "299999999999999999999999999999.97"
    assert stats["avg_amount"] == big


def test_analytics_summary_currency_filter():
    _create("10.00", "EUR")
    _create("20.00", "GBP")
    _create("30.00", "GBP")

    body = _summary(currency="GBP")

    assert body["total_transactions"] == 2
    assert [s["currency"] for s in body["per_currency"]] == ["GBP"]
    assert body["per_currency"][0]["total_amount"] == "50.00"
    assert body["status_counts"] == {"PENDING": 0, "COMPLETED": 2}


def test_analytics_summary_currency_filter_without_matches():
    _create("10.00", "EUR")
    body = _summary(currency="USD")
    assert body["total_transactions"] == 0
    assert body["per_currency"] == []


def test_analytics_summary_date_range_is_inclusive():
    day = datetime(2026, 11, 1, tzinfo=UTC)
    _create("1.00", created_at=day - timedelta(microseconds=1))
    _create("2.00", created_at=day)
    _create("3.00", created_at=day + timedelta(hours=12))
    _create("4.00", created_at=day + timedelta(days=1))
    _create("5.00", created_at=day + timedelta(days=1, microseconds=1))

    body = _summary(from_date=day.isoformat(), to_date=(day + timedelta(days=1)).isoformat())

    assert body["total_transactions"] == 3
    assert body["per_currency"][0]["total_amount"] == "9.00"
    assert _summary(from_date=day.isoformat())["total_transactions"] == 4
    assert _summary(to_date=day.isoformat())["total_transactions"] == 2


def test_analytics_summary_naive_dates_are_utc():
    day = datetime(2026, 11, 1, tzinfo=UTC)
    _create("1.00", created_at=day)
    _create("2.00", created_at=day + timedelta(seconds=1))
    assert _summary(from_date="2026-11-01T00:00:01")["total_transactions"] == 1
    assert _summary(to_date="2026-11-01T00:00:00")["total_transactions"] == 1


def test_analytics_summary_rejects_inverted_date_range():
    response = client.get(
        "/analytics/summary",
        params={"from_date": "2026-11-02T00:00:00Z", "to_date": "2026-11-01T00:00:00Z"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("params", [{"currency": "JPY"}, {"currency": "eur"}, {"from_date": "x"}])
def test_analytics_summary_rejects_invalid_params(params):
    assert client.get("/analytics/summary", params=params).status_code == 422


def test_analytics_summary_reflects_new_transactions():
    assert _summary()["total_transactions"] == 0
    _create("10.00")
    assert _summary()["total_transactions"] == 1
    _create("5.00", "USD")
    body = _summary()
    assert body["total_transactions"] == 2
    assert [s["currency"] for s in body["per_currency"]] == ["EUR", "USD"]

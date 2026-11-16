from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import _transactions, app, reset_store
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


def _create(at: datetime | None = None, **overrides):
    body = client.post("/transactions", json={**SAMPLE_TX, **overrides}).json()
    if at is not None:
        _transactions[body["id"]] = _transactions[body["id"]].model_copy(update={"created_at": at})
    return body


def test_analytics_summary_empty_store():
    response = client.get("/analytics/summary")
    assert response.status_code == 200
    assert response.json() == {"count": 0, "breakdowns": []}


def test_analytics_summary_multiple_currencies():
    _create(amount="125.50", currency="EUR")
    _create(amount="10.00", currency="EUR")
    _create(amount="0.01", currency="EUR")
    _create(amount="99.99", currency="GBP")

    response = client.get("/analytics/summary")
    assert response.status_code == 200
    assert response.json() == {
        "count": 4,
        "breakdowns": [
            {
                "currency": "EUR",
                "count": 3,
                "total_amount": "135.51",
                "min_amount": "0.01",
                "max_amount": "125.50",
                "avg_amount": "45.17",
            },
            {
                "currency": "GBP",
                "count": 1,
                "total_amount": "99.99",
                "min_amount": "99.99",
                "max_amount": "99.99",
                "avg_amount": "99.99",
            },
        ],
    }


def test_analytics_summary_average_rounds_half_up():
    _create(amount="0.01", currency="USD")
    _create(amount="0.02", currency="USD")
    usd = client.get("/analytics/summary").json()["breakdowns"][0]
    assert usd["avg_amount"] == "0.02"


def test_analytics_summary_large_amounts_are_exact():
    _create(amount="1E+40", currency="USD")
    _create(amount="0.01", currency="USD")
    usd = client.get("/analytics/summary").json()["breakdowns"][0]
    assert usd["total_amount"] == "1" + "0" * 40 + ".01"
    assert usd["avg_amount"] == "5" + "0" * 39 + ".01"


def test_analytics_summary_currency_filter():
    _create(currency="EUR")
    _create(amount="5.00", currency="USD")

    body = client.get("/analytics/summary", params={"currency": "USD"}).json()
    assert body["count"] == 1
    assert [b["currency"] for b in body["breakdowns"]] == ["USD"]
    assert body["breakdowns"][0]["total_amount"] == "5.00"


def test_analytics_summary_rejects_unknown_currency():
    assert client.get("/analytics/summary", params={"currency": "JPY"}).status_code == 422


def test_analytics_summary_since_until_filtering():
    _create(at=datetime(2026, 1, 1, tzinfo=UTC), amount="1.00")
    _create(at=datetime(2026, 2, 1, tzinfo=UTC), amount="2.00")
    _create(at=datetime(2026, 3, 1, tzinfo=UTC), amount="4.00")

    def total(**params):
        body = client.get("/analytics/summary", params=params).json()
        return body["count"], [b["total_amount"] for b in body["breakdowns"]]

    assert total(since="2026-02-01T00:00:00Z") == (2, ["6.00"])
    assert total(until="2026-02-01T00:00:00Z") == (2, ["3.00"])
    assert total(since="2026-01-15T00:00:00Z", until="2026-02-15T00:00:00Z") == (1, ["2.00"])
    assert total(since="2026-04-01T00:00:00Z") == (0, [])
    # Naive datetimes are treated as UTC.
    assert total(since="2026-02-01T00:00:00") == (2, ["6.00"])


def test_analytics_summary_rejects_since_after_until():
    response = client.get(
        "/analytics/summary",
        params={"since": "2026-03-01T00:00:00Z", "until": "2026-01-01T00:00:00Z"},
    )
    assert response.status_code == 422


def test_analytics_by_account():
    account = SAMPLE_TX["from_account"]
    other = SAMPLE_TX["to_account"]
    _create(amount="100.00", currency="EUR")
    _create(amount="25.25", currency="EUR")
    _create(amount="7.00", currency="GBP")
    _create(from_account=other, to_account=account, amount="3.50", currency="USD")

    response = client.get(f"/analytics/by-account/{account}")
    assert response.status_code == 200
    assert response.json() == {
        "account": account,
        "sent_count": 3,
        "received_count": 1,
        "sent_total": {"EUR": "125.25", "GBP": "7.00"},
        "received_total": {"USD": "3.50"},
    }


def test_analytics_by_account_unknown_is_404():
    _create()
    response = client.get("/analytics/by-account/NO_SUCH_ACCOUNT")
    assert response.status_code == 404
    assert response.json() == {"detail": "No transactions for account NO_SUCH_ACCOUNT"}


@pytest.mark.parametrize("param", ["since", "until"])
def test_analytics_summary_rejects_malformed_datetime(param):
    response = client.get("/analytics/summary", params={param: "not-a-date"})
    assert response.status_code == 422


def test_analytics_summary_currency_filter_without_matches():
    _create(currency="EUR")
    body = client.get("/analytics/summary", params={"currency": "GBP"}).json()
    assert body == {"count": 0, "breakdowns": []}


def test_analytics_summary_combined_currency_and_date_filters():
    _create(at=datetime(2026, 1, 1, tzinfo=UTC), amount="1.00", currency="USD")
    _create(at=datetime(2026, 2, 1, tzinfo=UTC), amount="2.00", currency="USD")
    _create(at=datetime(2026, 2, 1, tzinfo=UTC), amount="8.00", currency="EUR")

    body = client.get(
        "/analytics/summary", params={"currency": "USD", "since": "2026-01-15T00:00:00Z"}
    ).json()
    assert body["count"] == 1
    assert [(b["currency"], b["total_amount"]) for b in body["breakdowns"]] == [("USD", "2.00")]


def test_analytics_summary_bounds_with_utc_offset_and_naive_until():
    _create(at=datetime(2026, 2, 1, 12, 0, tzinfo=UTC), amount="2.00")

    def count(**params):
        return client.get("/analytics/summary", params=params).json()["count"]

    # 14:00+02:00 == 12:00Z, and bounds are inclusive.
    assert count(since="2026-02-01T14:00:00+02:00") == 1
    assert count(since="2026-02-01T14:00:01+02:00") == 0
    assert count(until="2026-02-01T14:00:00+02:00") == 1
    assert count(until="2026-02-01T13:59:59+02:00") == 0
    # Naive `until` is treated as UTC.
    assert count(until="2026-02-01T12:00:00") == 1
    assert count(until="2026-02-01T11:59:59") == 0
    # since == until selects exactly that instant.
    assert count(since="2026-02-01T12:00:00Z", until="2026-02-01T12:00:00Z") == 1


@pytest.mark.parametrize(
    ("amounts", "expected_avg"),
    [
        (["0.005"], "0.01"),
        (["0.004"], "0.00"),
        (["2.675"], "2.68"),
        (["0.333", "0.333", "0.334"], "0.33"),
        (["0.001", "0.002", "0.002"], "0.00"),
    ],
)
def test_analytics_summary_average_sub_cent_amounts(amounts, expected_avg):
    for amount in amounts:
        _create(amount=amount, currency="GBP")
    gbp = client.get("/analytics/summary").json()["breakdowns"][0]
    assert gbp["avg_amount"] == expected_avg


def test_analytics_by_account_receive_only():
    account = SAMPLE_TX["to_account"]
    _create(amount="40.00", currency="EUR")
    _create(amount="2.50", currency="EUR")

    response = client.get(f"/analytics/by-account/{account}")
    assert response.status_code == 200
    assert response.json() == {
        "account": account,
        "sent_count": 0,
        "received_count": 2,
        "sent_total": {},
        "received_total": {"EUR": "42.50"},
    }


def test_analytics_by_account_empty_store_is_404():
    response = client.get(f"/analytics/by-account/{SAMPLE_TX['from_account']}")
    assert response.status_code == 404

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import Currency, Transaction, TransactionStatus, _transactions, app, reset_store
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


def _insert_tx(tx_id, amount, currency, created_at, status=TransactionStatus.COMPLETED, **kw):
    tx = Transaction(
        id=tx_id,
        status=status,
        created_at=created_at,
        from_account=kw.get("from_account", "ACC-A"),
        to_account=kw.get("to_account", "ACC-B"),
        amount=Decimal(amount),
        currency=currency,
    )
    _transactions[tx.id] = tx
    return tx


def test_analytics_summary_empty_store():
    response = client.get("/analytics/summary")
    assert response.status_code == 200
    assert response.json() == {
        "total_transactions": 0,
        "total_amount_by_currency": {"EUR": "0", "GBP": "0", "USD": "0"},
        "count_by_status": {"PENDING": 0, "COMPLETED": 0},
        "count_by_currency": {"EUR": 0, "GBP": 0, "USD": 0},
        "average_amount": None,
        "largest_transaction": None,
        "first_transaction_at": None,
        "last_transaction_at": None,
    }


def test_analytics_summary_after_posting_transactions():
    created = [
        client.post("/transactions", json=SAMPLE_TX).json(),
        client.post("/transactions", json={**SAMPLE_TX, "amount": "10.00"}).json(),
        client.post("/transactions", json={**SAMPLE_TX, "amount": "300", "currency": "USD"}).json(),
    ]

    response = client.get("/analytics/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["total_transactions"] == 3
    assert body["total_amount_by_currency"] == {"EUR": "135.50", "GBP": "0", "USD": "300"}
    assert body["count_by_currency"] == {"EUR": 2, "GBP": 0, "USD": 1}
    assert body["count_by_status"] == {"PENDING": 0, "COMPLETED": 3}
    assert body["average_amount"] == "145.17"
    assert body["largest_transaction"] == created[2]
    assert body["first_transaction_at"] == min(tx["created_at"] for tx in created)
    assert body["last_transaction_at"] == max(tx["created_at"] for tx in created)
    assert body["first_transaction_at"] <= body["last_transaction_at"]


def test_analytics_summary_counts_pending_and_orders_timestamps():
    _insert_tx("late", "5", Currency.GBP, datetime(2026, 3, 1, tzinfo=UTC))
    _insert_tx(
        "early", "5", Currency.GBP, datetime(2026, 1, 1, tzinfo=UTC), TransactionStatus.PENDING
    )

    body = client.get("/analytics/summary").json()
    assert body["count_by_status"] == {"PENDING": 1, "COMPLETED": 1}
    assert body["first_transaction_at"] == "2026-01-01T00:00:00Z"
    assert body["last_transaction_at"] == "2026-03-01T00:00:00Z"
    assert body["largest_transaction"]["id"] == "early"


def test_analytics_summary_average_rounds_half_even():
    _insert_tx("a", "0.01", Currency.EUR, datetime(2026, 1, 1, tzinfo=UTC))
    _insert_tx("b", "0.04", Currency.EUR, datetime(2026, 1, 2, tzinfo=UTC))
    assert client.get("/analytics/summary").json()["average_amount"] == "0.02"


def test_analytics_summary_stays_exact_for_huge_amounts():
    huge = "1" + "0" * 40 + ".01"
    _insert_tx("a", huge, Currency.EUR, datetime(2026, 1, 1, tzinfo=UTC))
    _insert_tx("b", "0.01", Currency.EUR, datetime(2026, 1, 2, tzinfo=UTC))

    body = client.get("/analytics/summary").json()
    assert body["total_amount_by_currency"]["EUR"] == "1" + "0" * 40 + ".02"
    assert body["average_amount"] == "5" + "0" * 39 + ".01"


def test_analytics_summary_filters():
    _insert_tx("jan", "10", Currency.EUR, datetime(2026, 1, 1, tzinfo=UTC), to_account="ACC-X")
    _insert_tx("feb", "20", Currency.USD, datetime(2026, 2, 1, tzinfo=UTC), from_account="ACC-X")
    _insert_tx("mar", "30", Currency.EUR, datetime(2026, 3, 1, tzinfo=UTC))

    def summary(**params):
        response = client.get("/analytics/summary", params=params)
        assert response.status_code == 200
        return response.json()

    assert summary(currency="EUR")["total_amount_by_currency"]["EUR"] == "40"
    assert summary(currency="EUR")["count_by_currency"] == {"EUR": 2, "GBP": 0, "USD": 0}
    window = summary(since="2026-02-01T00:00:00Z", until="2026-03-01T00:00:00Z")
    assert window["total_transactions"] == 2
    assert window["largest_transaction"]["id"] == "mar"
    assert summary(since="2026-02-01T00:00:00")["first_transaction_at"] == "2026-02-01T00:00:00Z"
    by_account = summary(account="ACC-X")
    assert by_account["total_transactions"] == 2
    assert by_account["last_transaction_at"] == "2026-02-01T00:00:00Z"
    assert summary(account="nobody")["average_amount"] is None


@pytest.mark.parametrize(
    "params",
    [
        {"since": "2026-03-01T00:00:00Z", "until": "2026-01-01T00:00:00Z"},
        {"since": "not-a-date"},
        {"currency": "JPY"},
        {"account": ""},
    ],
)
def test_analytics_summary_rejects_invalid_params(params):
    assert client.get("/analytics/summary", params=params).status_code == 422

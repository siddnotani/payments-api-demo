from datetime import UTC, datetime
from uuid import uuid4

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


def _insert_tx(amount: str, currency: str, tx_status: TransactionStatus) -> None:
    tx = Transaction(
        id=str(uuid4()),
        status=tx_status,
        created_at=datetime.now(UTC),
        **{**SAMPLE_TX, "amount": amount, "currency": currency},
    )
    _transactions[tx.id] = tx


def test_analytics_summary_empty_store():
    response = client.get("/analytics/summary")
    assert response.status_code == 200
    assert response.json() == {
        "total_transactions": 0,
        "by_currency": {},
        "by_status": {"PENDING": 0, "COMPLETED": 0},
    }


def test_analytics_summary_multiple_currencies_and_statuses():
    _insert_tx("10.00", "EUR", TransactionStatus.COMPLETED)
    _insert_tx("30.00", "EUR", TransactionStatus.PENDING)
    _insert_tx("5.25", "USD", TransactionStatus.COMPLETED)
    client.post("/transactions", json={**SAMPLE_TX, "amount": "20.00", "currency": "GBP"})

    body = client.get("/analytics/summary").json()
    assert body["total_transactions"] == 4
    assert body["by_status"] == {"PENDING": 1, "COMPLETED": 3}
    assert body["by_currency"] == {
        "EUR": {"count": 2, "total": "40.00", "min": "10.00", "max": "30.00", "average": "20.00"},
        "GBP": {"count": 1, "total": "20.00", "min": "20.00", "max": "20.00", "average": "20.00"},
        "USD": {"count": 1, "total": "5.25", "min": "5.25", "max": "5.25", "average": "5.25"},
    }


def test_analytics_summary_average_rounds_non_terminating_division():
    for amount in ("10.00", "10.00", "11.00"):
        _insert_tx(amount, "EUR", TransactionStatus.COMPLETED)

    eur = client.get("/analytics/summary").json()["by_currency"]["EUR"]
    assert eur["total"] == "31.00"
    assert eur["average"] == "10.33"


def test_analytics_summary_average_keeps_input_precision():
    _insert_tx("0.001", "USD", TransactionStatus.COMPLETED)
    _insert_tx("0.002", "USD", TransactionStatus.COMPLETED)

    usd = client.get("/analytics/summary").json()["by_currency"]["USD"]
    assert usd["total"] == "0.003"
    assert usd["average"] == "0.002"


def test_analytics_summary_large_amounts_are_exact():
    big = "1" + "0" * 40 + ".01"
    _insert_tx(big, "EUR", TransactionStatus.COMPLETED)
    _insert_tx(big, "EUR", TransactionStatus.COMPLETED)

    eur = client.get("/analytics/summary").json()["by_currency"]["EUR"]
    assert eur["total"] == "2" + "0" * 40 + ".02"
    assert eur["average"] == big


def test_analytics_summary_currency_filter():
    _insert_tx("10.00", "EUR", TransactionStatus.COMPLETED)
    _insert_tx("20.00", "EUR", TransactionStatus.PENDING)
    _insert_tx("99.99", "USD", TransactionStatus.COMPLETED)

    body = client.get("/analytics/summary", params={"currency": "EUR"}).json()
    assert body["total_transactions"] == 2
    assert list(body["by_currency"]) == ["EUR"]
    assert body["by_currency"]["EUR"]["average"] == "15.00"
    assert body["by_status"] == {"PENDING": 1, "COMPLETED": 1}


def test_analytics_summary_currency_filter_with_no_matches():
    _insert_tx("10.00", "EUR", TransactionStatus.COMPLETED)

    body = client.get("/analytics/summary", params={"currency": "GBP"}).json()
    assert body == {
        "total_transactions": 0,
        "by_currency": {},
        "by_status": {"PENDING": 0, "COMPLETED": 0},
    }


def test_analytics_summary_rejects_unknown_currency():
    assert client.get("/analytics/summary", params={"currency": "JPY"}).status_code == 422


@pytest.mark.parametrize(
    ("amounts", "expected_average"),
    [
        (("0.01", "0.04"), "0.02"),
        (("0.01", "0.02"), "0.02"),
        (("0.10", "0.25"), "0.18"),
    ],
)
def test_analytics_summary_average_rounds_half_even(amounts, expected_average):
    for amount in amounts:
        _insert_tx(amount, "EUR", TransactionStatus.COMPLETED)

    eur = client.get("/analytics/summary").json()["by_currency"]["EUR"]
    assert eur["average"] == expected_average


def test_analytics_summary_average_has_at_least_two_decimal_places():
    _insert_tx("10", "USD", TransactionStatus.COMPLETED)
    _insert_tx("11", "USD", TransactionStatus.COMPLETED)

    usd = client.get("/analytics/summary").json()["by_currency"]["USD"]
    assert usd["total"] == "21"
    assert usd["average"] == "10.50"


def test_analytics_summary_currencies_are_sorted():
    for currency in ("USD", "EUR", "GBP"):
        client.post("/transactions", json={**SAMPLE_TX, "currency": currency})

    body = client.get("/analytics/summary").json()
    assert list(body["by_currency"]) == ["EUR", "GBP", "USD"]


@pytest.mark.parametrize("currency", ["eur", ""])
def test_analytics_summary_rejects_invalid_currency_values(currency):
    response = client.get("/analytics/summary", params={"currency": currency})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "currency"]

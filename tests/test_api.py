import subprocess
import sys
from pathlib import Path

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
        "per_currency": [],
        "largest_transaction": None,
    }


def test_analytics_summary_groups_by_currency():
    for amount, currency in [
        ("100.00", "EUR"),
        ("50.25", "EUR"),
        ("10.00", "EUR"),
        ("200.00", "GBP"),
        ("1.00", "USD"),
        ("2.00", "USD"),
    ]:
        client.post("/transactions", json={**SAMPLE_TX, "amount": amount, "currency": currency})

    response = client.get("/analytics/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["total_transactions"] == 6
    assert body["per_currency"] == [
        {"currency": "EUR", "count": 3, "total_amount": "160.25", "average_amount": "53.42"},
        {"currency": "GBP", "count": 1, "total_amount": "200.00", "average_amount": "200.00"},
        {"currency": "USD", "count": 2, "total_amount": "3.00", "average_amount": "1.50"},
    ]
    assert body["largest_transaction"]["amount"] == "200.00"
    assert body["largest_transaction"]["currency"] == "GBP"


def test_analytics_summary_largest_tie_returns_earliest():
    first = client.post("/transactions", json={**SAMPLE_TX, "amount": "5.00"}).json()
    client.post("/transactions", json={**SAMPLE_TX, "amount": "5.00"})
    body = client.get("/analytics/summary").json()
    assert body["largest_transaction"]["id"] == first["id"]


def test_analytics_summary_filters_by_account():
    client.post("/transactions", json={**SAMPLE_TX, "from_account": "ACC-A", "to_account": "ACC-B"})
    client.post(
        "/transactions",
        json={**SAMPLE_TX, "from_account": "ACC-C", "to_account": "ACC-A", "amount": "300.00"},
    )
    client.post(
        "/transactions",
        json={**SAMPLE_TX, "from_account": "ACC-B", "to_account": "ACC-C", "amount": "999.00"},
    )

    body = client.get("/analytics/summary", params={"account": "ACC-A"}).json()
    assert body["total_transactions"] == 2
    assert body["per_currency"] == [
        {"currency": "EUR", "count": 2, "total_amount": "425.50", "average_amount": "212.75"},
    ]
    assert body["largest_transaction"]["amount"] == "300.00"

    unknown = client.get("/analytics/summary", params={"account": "ACC-Z"}).json()
    assert unknown == {"total_transactions": 0, "per_currency": [], "largest_transaction": None}


def test_analytics_summary_rejects_empty_account():
    assert client.get("/analytics/summary", params={"account": ""}).status_code == 422


def test_analytics_summary_handles_large_amounts():
    big = "9" * 40 + ".99"
    client.post("/transactions", json={**SAMPLE_TX, "amount": big})
    client.post("/transactions", json={**SAMPLE_TX, "amount": "0.01"})
    body = client.get("/analytics/summary").json()
    eur = body["per_currency"][0]
    assert eur["total_amount"] == "1" + "0" * 40 + ".00"
    assert eur["average_amount"] == "5" + "0" * 39 + ".00"
    assert body["largest_transaction"]["amount"] == big


def test_analytics_summary_rounds_half_up():
    client.post("/transactions", json={**SAMPLE_TX, "amount": "0.125"})
    body = client.get("/analytics/summary").json()
    assert body["per_currency"][0]["total_amount"] == "0.13"
    assert body["per_currency"][0]["average_amount"] == "0.13"

    reset_store()
    client.post("/transactions", json={**SAMPLE_TX, "amount": "0.01"})
    client.post("/transactions", json={**SAMPLE_TX, "amount": "0.04"})
    eur = client.get("/analytics/summary").json()["per_currency"][0]
    assert eur["total_amount"] == "0.05"
    assert eur["average_amount"] == "0.03"


def test_analytics_summary_sums_sub_cent_amounts_before_rounding():
    for _ in range(3):
        client.post("/transactions", json={**SAMPLE_TX, "amount": "0.005"})
    eur = client.get("/analytics/summary").json()["per_currency"][0]
    assert eur == {"currency": "EUR", "count": 3, "total_amount": "0.02", "average_amount": "0.01"}


def test_analytics_summary_account_filter_requires_exact_match():
    client.post("/transactions", json={**SAMPLE_TX, "from_account": "ACC-A", "to_account": "ACC-B"})
    for account in ["ACC", "acc-a", "ACC-A "]:
        body = client.get("/analytics/summary", params={"account": account}).json()
        assert body["total_transactions"] == 0, account


def test_analytics_summary_largest_transaction_matches_stored_record():
    created = client.post("/transactions", json=SAMPLE_TX).json()
    largest = client.get("/analytics/summary").json()["largest_transaction"]
    assert largest == created
    assert largest == client.get(f"/transactions/{created['id']}").json()


@pytest.mark.xfail(
    strict=True,
    reason="Decimal(int) in _round_cents is quadratic: amount '1E+1000000' stalls the summary ~15s",
)
def test_analytics_summary_large_exponent_amount_is_bounded():
    script = (
        "from fastapi.testclient import TestClient\n"
        "from app.main import app\n"
        "c = TestClient(app)\n"
        "tx = {'from_account': 'A', 'to_account': 'B', 'amount': '1E+1000000'}\n"
        "assert c.post('/transactions', json=tx).status_code == 201\n"
        "assert c.get('/analytics/summary').status_code == 200\n"
    )
    try:
        subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("GET /analytics/summary did not finish within 5s")

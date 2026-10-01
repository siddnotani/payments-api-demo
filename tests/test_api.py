import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.scheduler import JobResult, job
from app.store import reset_store

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


def fund(currency="EUR", amount="1000.00", account=SAMPLE_TX["from_account"]):
    response = client.post(
        f"/accounts/{account}/deposits", json={"amount": amount, "currency": currency}
    )
    assert response.status_code == 201


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "transactions": 0, "accounts": 0}


def test_create_transaction():
    fund()
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

    fund()
    client.post("/transactions", json=SAMPLE_TX)
    client.post("/transactions", json={**SAMPLE_TX, "amount": "10.00"})

    response = client.get("/transactions")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 3
    assert [tx["amount"] for tx in body] == ["1000.00", "125.50", "10.00"]


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


def test_health_counts_stored_transactions():
    fund()
    client.post("/transactions", json=SAMPLE_TX)
    client.post("/transactions", json={**SAMPLE_TX, "amount": "10.00"})
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "transactions": 3, "accounts": 2}


def test_get_transaction_by_id():
    fund()
    created = client.post("/transactions", json=SAMPLE_TX).json()
    response = client.get(f"/transactions/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_get_unknown_transaction_is_404():
    response = client.get("/transactions/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"detail": "Transaction does-not-exist not found"}


def test_create_transaction_defaults():
    fund()
    payload = {k: v for k, v in SAMPLE_TX.items() if k not in ("currency", "reference")}
    response = client.post("/transactions", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["currency"] == "EUR"
    assert body["reference"] is None
    assert body["created_at"]


def test_create_transaction_same_account_detail():
    payload = {**SAMPLE_TX, "to_account": SAMPLE_TX["from_account"]}
    response = client.post("/transactions", json=payload)
    assert response.json() == {"detail": "from_account and to_account must differ"}
    assert client.get("/health").json()["transactions"] == 0


def test_create_transaction_rejects_negative_amount():
    response = client.post("/transactions", json={**SAMPLE_TX, "amount": "-5.00"})
    assert response.status_code == 422


@pytest.mark.parametrize("field", ["from_account", "to_account"])
def test_create_transaction_rejects_empty_account(field):
    response = client.post("/transactions", json={**SAMPLE_TX, field: ""})
    assert response.status_code == 422


@pytest.mark.parametrize("field", ["from_account", "to_account", "amount"])
def test_create_transaction_rejects_missing_required_field(field):
    payload = {k: v for k, v in SAMPLE_TX.items() if k != field}
    response = client.post("/transactions", json=payload)
    assert response.status_code == 422


@pytest.mark.parametrize("currency", ["GBP", "USD"])
def test_create_transaction_accepts_supported_currencies(currency):
    fund(currency)
    response = client.post("/transactions", json={**SAMPLE_TX, "currency": currency})
    assert response.status_code == 201
    assert response.json()["currency"] == currency


def test_create_transaction_rejects_unsupported_currency():
    response = client.post("/transactions", json={**SAMPLE_TX, "currency": "JPY"})
    assert response.status_code == 422


def test_create_transaction_reference_max_length():
    fund()
    ok = client.post("/transactions", json={**SAMPLE_TX, "reference": "x" * 140})
    assert ok.status_code == 201
    too_long = client.post("/transactions", json={**SAMPLE_TX, "reference": "x" * 141})
    assert too_long.status_code == 422

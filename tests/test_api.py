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


@pytest.mark.parametrize(
    "account",
    [
        "X" * 10_000,
        "GB29NWBK60161331926819,EVIL",
        "GB29NWBK60161331926819\nid,ES91,GB29,9999,EUR",
        "=HYPERLINK(1)",
        "not an iban",
    ],
)
def test_create_transaction_rejects_malformed_account(account):
    response = client.post("/transactions", json={**SAMPLE_TX, "to_account": account})
    assert response.status_code == 422
    assert client.get("/transactions").json() == []


@pytest.mark.parametrize("amount", ["1e400", "Infinity", "NaN", "1000000000.01", "1.005"])
def test_create_transaction_rejects_out_of_range_amount(amount):
    response = client.post("/transactions", json={**SAMPLE_TX, "amount": amount})
    assert response.status_code == 422


def test_create_transaction_normalizes_accounts():
    payload = {**SAMPLE_TX, "from_account": " es9121000418450200051332 "}
    response = client.post("/transactions", json=payload)
    assert response.status_code == 201
    assert response.json()["from_account"] == "ES9121000418450200051332"


def test_create_transaction_rejects_same_account_after_normalization():
    payload = {**SAMPLE_TX, "to_account": SAMPLE_TX["from_account"].lower() + " "}
    response = client.post("/transactions", json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": "from_account and to_account must differ"}


def test_create_transaction_rejects_when_store_full(monkeypatch):
    monkeypatch.setattr("app.main.MAX_STORED_TRANSACTIONS", 2)
    assert client.post("/transactions", json=SAMPLE_TX).status_code == 201
    assert client.post("/transactions", json=SAMPLE_TX).status_code == 201
    response = client.post("/transactions", json=SAMPLE_TX)
    assert response.status_code == 507
    assert response.json() == {"detail": "Transaction store is full (2 records)"}
    assert client.get("/health").json()["transactions"] == 2


@pytest.mark.parametrize("account", ["X" * 10_000, "GB29NWBK60161331926819,EVIL", "not an iban"])
def test_create_transaction_rejects_malformed_from_account(account):
    response = client.post("/transactions", json={**SAMPLE_TX, "from_account": account})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "from_account"]
    assert client.get("/transactions").json() == []


@pytest.mark.parametrize(
    ("account", "expected_status"),
    [
        ("GB29" + "A" * 10, 422),
        ("GB29" + "A" * 11, 201),
        ("GB29" + "A" * 30, 201),
        ("GB29" + "A" * 31, 422),
    ],
)
def test_create_transaction_account_length_boundaries(account, expected_status):
    response = client.post("/transactions", json={**SAMPLE_TX, "to_account": account})
    assert response.status_code == expected_status


def test_create_transaction_rejects_non_string_account():
    response = client.post("/transactions", json={**SAMPLE_TX, "to_account": 1234567890123456})
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "string_type"


@pytest.mark.parametrize("field", ["from_account", "to_account", "amount"])
def test_create_transaction_rejects_missing_required_field(field):
    payload = {k: v for k, v in SAMPLE_TX.items() if k != field}
    response = client.post("/transactions", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "missing"


def test_create_transaction_normalizes_to_account():
    payload = {**SAMPLE_TX, "to_account": "\tgb29nwbk60161331926819 "}
    response = client.post("/transactions", json=payload)
    assert response.status_code == 201
    assert response.json()["to_account"] == "GB29NWBK60161331926819"


@pytest.mark.parametrize("amount", ["0.01", "1000000000.00"])
def test_create_transaction_accepts_amount_at_limits(amount):
    response = client.post("/transactions", json={**SAMPLE_TX, "amount": amount})
    assert response.status_code == 201
    assert response.json()["amount"] == amount


def test_create_transaction_rejects_negative_amount():
    response = client.post("/transactions", json={**SAMPLE_TX, "amount": "-1.00"})
    assert response.status_code == 422


def test_create_transaction_same_account_checked_before_store_full(monkeypatch):
    monkeypatch.setattr("app.main.MAX_STORED_TRANSACTIONS", 0)
    payload = {**SAMPLE_TX, "to_account": SAMPLE_TX["from_account"]}
    response = client.post("/transactions", json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": "from_account and to_account must differ"}


@pytest.mark.parametrize(
    ("amount", "expected"),
    [("1.500", "1.50"), ("125.5000000", "125.50"), ("1E+2", "100.00"), ("7", "7.00")],
)
def test_create_transaction_amount_is_canonical_two_decimal(amount, expected):
    response = client.post("/transactions", json={**SAMPLE_TX, "amount": amount})
    assert response.status_code == 201
    assert response.json()["amount"] == expected
    assert client.get("/transactions").json()[0]["amount"] == expected

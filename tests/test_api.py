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


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("0.12345678901234567890", "0.12345678901234567890"),
        ("1e400", "1E+400"),
    ],
)
def test_create_transaction_preserves_numeric_amount(amount, expected):
    with TestClient(app, raise_server_exceptions=False) as api:
        response = api.post(
            "/transactions",
            content=f'{{"from_account":"A","to_account":"B","amount":{amount}}}',
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 201
    assert response.json()["amount"] == expected


def test_create_transaction_rejects_large_negative_numeric_amount():
    with TestClient(app, raise_server_exceptions=False) as api:
        response = api.post(
            "/transactions",
            content='{"from_account":"A","to_account":"B","amount":-1e5000}',
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 422


def _post_raw_transaction(body):
    with TestClient(app, raise_server_exceptions=False) as api:
        return api.post(
            "/transactions",
            content=body,
            headers={"Content-Type": "application/json"},
        )


def test_create_transaction_numeric_amount_round_trips():
    response = _post_raw_transaction(
        '{"from_account":"A","to_account":"B","amount":0.12345678901234567890}'
    )
    assert response.status_code == 201
    tx_id = response.json()["id"]

    fetched = client.get(f"/transactions/{tx_id}")
    assert fetched.status_code == 200
    assert fetched.json()["amount"] == "0.12345678901234567890"
    assert [tx["amount"] for tx in client.get("/transactions").json()] == ["0.12345678901234567890"]


def test_create_transaction_accepts_integer_numeric_amount():
    response = _post_raw_transaction('{"from_account":"A","to_account":"B","amount":100}')
    assert response.status_code == 201
    assert response.json()["amount"] == "100"


@pytest.mark.parametrize(
    ("amount", "expected_input"),
    [
        ("0", 0),
        ("0.0", "0.0"),
        ("-1.5", "-1.5"),
        ("-1e5000", "-1E+5000"),
    ],
)
def test_create_transaction_rejects_non_positive_numeric_amount(amount, expected_input):
    response = _post_raw_transaction(f'{{"from_account":"A","to_account":"B","amount":{amount}}}')
    assert response.status_code == 422
    (error,) = response.json()["detail"]
    assert error["type"] == "greater_than"
    assert error["loc"] == ["body", "amount"]
    assert error["input"] == expected_input
    assert error["ctx"] == {"gt": "0"}


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity"])
def test_create_transaction_rejects_non_finite_numeric_amount(amount):
    response = _post_raw_transaction(f'{{"from_account":"A","to_account":"B","amount":{amount}}}')
    assert response.status_code == 422
    (error,) = response.json()["detail"]
    assert error["type"] == "finite_number"
    assert error["loc"] == ["body", "amount"]
    assert error["input"] == amount


def test_create_transaction_rejects_malformed_json():
    response = _post_raw_transaction('{"from_account":"A",')
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "json_invalid"


def test_create_transaction_rejects_same_account_numeric_amount():
    response = _post_raw_transaction('{"from_account":"A","to_account":"A","amount":1.5}')
    assert response.status_code == 422
    assert response.json() == {"detail": "from_account and to_account must differ"}


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"from_account": ""}, "from_account"),
        ({"to_account": ""}, "to_account"),
        ({"currency": "JPY"}, "currency"),
        ({"reference": "x" * 141}, "reference"),
        ({"amount": "abc"}, "amount"),
        ({"amount": None}, "amount"),
    ],
)
def test_create_transaction_rejects_invalid_fields(overrides, field):
    response = client.post("/transactions", json={**SAMPLE_TX, **overrides})
    assert response.status_code == 422
    (error,) = response.json()["detail"]
    assert error["loc"] == ["body", field]


def test_create_transaction_rejects_missing_amount():
    payload = {k: v for k, v in SAMPLE_TX.items() if k != "amount"}
    response = client.post("/transactions", json=payload)
    assert response.status_code == 422
    (error,) = response.json()["detail"]
    assert error["type"] == "missing"
    assert error["loc"] == ["body", "amount"]


def test_openapi_documents_create_transaction():
    operation = client.get("/openapi.json").json()["paths"]["/transactions"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/TransactionCreate"
    }
    assert set(operation["responses"]) == {"201", "422"}


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

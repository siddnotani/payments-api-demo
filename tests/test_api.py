from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from app import main as payments
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


def test_list_transactions_preserves_json_bytes_and_schema():
    first = client.post("/transactions", json={**SAMPLE_TX, "reference": 'Café "☕"\n'})
    assert first.status_code == 201
    assert client.get("/transactions").content == b"[" + first.content + b"]"

    payload = {**SAMPLE_TX, "currency": "USD", "reference": None}
    second = client.post("/transactions", json=payload)
    assert second.status_code == 201

    response = client.get("/transactions")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.content == b"[" + first.content + b"," + second.content + b"]"

    api = client.get("/openapi.json").json()
    schema = api["paths"]["/transactions"]["get"]["responses"]["200"]["content"]
    assert schema["application/json"]["schema"]["items"] == {
        "$ref": "#/components/schemas/Transaction"
    }

    reset_store()
    assert client.get("/transactions").content == b"[]"


def test_list_transactions_does_not_publish_snapshot_after_concurrent_write(monkeypatch):
    first = client.post("/transactions", json=SAMPLE_TX)
    assert first.status_code == 201
    serializing = Event()
    resume = Event()
    dump_json = payments._transaction_list_adapter.dump_json

    def pause_before_serializing(transactions):
        serializing.set()
        assert resume.wait(timeout=5)
        return dump_json(transactions)

    monkeypatch.setattr(payments._transaction_list_adapter, "dump_json", pause_before_serializing)
    with ThreadPoolExecutor() as executor:
        listing = executor.submit(client.get, "/transactions")
        try:
            assert serializing.wait(timeout=5)
            second = client.post("/transactions", json={**SAMPLE_TX, "amount": "10.00"})
            assert second.status_code == 201
        finally:
            resume.set()
        assert listing.result(timeout=5).content == b"[" + first.content + b"]"

    assert (
        client.get("/transactions").content == b"[" + first.content + b"," + second.content + b"]"
    )


def _count_list_serializations(monkeypatch):
    calls = []
    dump_json = payments._transaction_list_adapter.dump_json

    def counting_dump_json(transactions):
        calls.append(len(transactions))
        return dump_json(transactions)

    monkeypatch.setattr(payments._transaction_list_adapter, "dump_json", counting_dump_json)
    return calls


def test_list_transactions_reuses_cached_body_until_next_write(monkeypatch):
    calls = _count_list_serializations(monkeypatch)
    client.post("/transactions", json=SAMPLE_TX)

    first = client.get("/transactions")
    second = client.get("/transactions")
    assert first.status_code == second.status_code == 200
    assert second.content == first.content
    assert calls == [1]

    client.post("/transactions", json={**SAMPLE_TX, "amount": "10.00"})
    third = client.get("/transactions")
    assert [tx["amount"] for tx in third.json()] == ["125.50", "10.00"]
    assert calls == [1, 2]

    reset_store()
    assert client.get("/transactions").json() == []
    assert calls == [1, 2, 0]


@pytest.mark.parametrize(
    "overrides",
    [
        {"to_account": SAMPLE_TX["from_account"]},
        {"amount": "0"},
        {"amount": "-5.00"},
        {"from_account": ""},
        {"currency": "JPY"},
        {"reference": "x" * 141},
    ],
)
def test_rejected_create_does_not_invalidate_list_cache(monkeypatch, overrides):
    calls = _count_list_serializations(monkeypatch)
    client.post("/transactions", json=SAMPLE_TX)
    cached = client.get("/transactions").content

    response = client.post("/transactions", json={**SAMPLE_TX, **overrides})
    assert response.status_code == 422

    assert client.get("/transactions").content == cached
    assert calls == [1]


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

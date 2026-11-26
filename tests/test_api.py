import threading

import pytest
from fastapi.testclient import TestClient

from app import scheduler
from app.main import app, reset_store
from app.scheduler import (
    DEFAULT_TIMEOUT_SECONDS,
    JobContext,
    JobResult,
    JobTimeoutError,
    job,
    run_job,
)

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


@pytest.fixture
def isolated_jobs(monkeypatch):
    monkeypatch.setattr(scheduler, "_registry", dict(scheduler._registry))
    monkeypatch.setattr(scheduler, "_locks", dict(scheduler._locks))

    def register(name, fn, **kwargs):
        job(name, schedule="* * * * *", **kwargs)(fn)

    return register


def test_run_job_endpoint_passes_dry_run_to_job(isolated_jobs):
    seen = []

    def record(ctx: JobContext) -> JobResult:
        seen.append(ctx.dry_run)
        return JobResult(processed=1)

    isolated_jobs("record", record)
    assert client.post("/ops/jobs/record/run").status_code == 200
    assert client.post("/ops/jobs/record/run", params={"dry_run": "false"}).status_code == 200
    assert seen == [True, False]


def test_registered_job_uses_default_timeout():
    heartbeat = next(j for j in scheduler.registered_jobs() if j.name == "heartbeat")
    assert DEFAULT_TIMEOUT_SECONDS == 30.0
    assert heartbeat.timeout == DEFAULT_TIMEOUT_SECONDS


def test_run_job_409_does_not_invoke_job_again(isolated_jobs):
    calls = []
    started, release = threading.Event(), threading.Event()

    def slow(ctx: JobContext) -> JobResult:
        calls.append(ctx.dry_run)
        started.set()
        release.wait(5)
        return JobResult()

    isolated_jobs("slow_409", slow)
    first = threading.Thread(target=run_job, args=("slow_409",))
    first.start()
    try:
        assert started.wait(5)
        response = client.post("/ops/jobs/slow_409/run")
        assert response.status_code == 409
        assert response.json() == {"detail": "job 'slow_409' is already running"}
    finally:
        release.set()
        first.join(5)
    assert calls == [True]


def test_job_raising_timeout_error_is_not_reported_as_run_timeout(isolated_jobs):
    def upstream_timeout(ctx: JobContext) -> JobResult:
        raise TimeoutError("upstream FX feed timed out")

    isolated_jobs("upstream_timeout", upstream_timeout)
    with pytest.raises(TimeoutError, match="upstream FX feed") as excinfo:
        run_job("upstream_timeout")
    assert not isinstance(excinfo.value, JobTimeoutError)

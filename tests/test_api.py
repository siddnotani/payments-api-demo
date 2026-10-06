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
        "total_volume": {"EUR": "0", "GBP": "0", "USD": "0"},
        "average_amount": None,
        "largest_transaction": None,
        "top_accounts": [],
    }


def test_analytics_summary_aggregates_multiple_currencies():
    alice, bob, carol = "ACC-ALICE", "ACC-BOB", "ACC-CAROL"
    for from_account, to_account, amount, currency in [
        (alice, bob, "100.10", "EUR"),
        (alice, carol, "50.20", "EUR"),
        (bob, carol, "200.00", "USD"),
        (carol, alice, "0.05", "GBP"),
    ]:
        client.post(
            "/transactions",
            json={
                "from_account": from_account,
                "to_account": to_account,
                "amount": amount,
                "currency": currency,
            },
        )

    response = client.get("/analytics/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["total_transactions"] == 4
    assert body["total_volume"] == {"EUR": "150.30", "GBP": "0.05", "USD": "200.00"}
    # 350.35 / 4 = 87.5875, rounded half-even to cents.
    assert body["average_amount"] == "87.59"
    assert body["largest_transaction"]["amount"] == "200.00"
    assert body["largest_transaction"]["currency"] == "USD"
    # Alice and Carol tie on 3 and are ordered by account id.
    assert body["top_accounts"] == [
        {"account": alice, "transaction_count": 3},
        {"account": carol, "transaction_count": 3},
        {"account": bob, "transaction_count": 2},
    ]


def test_analytics_summary_limits_top_accounts():
    for i in range(7):
        client.post(
            "/transactions",
            json={**SAMPLE_TX, "from_account": "ACC-HUB", "to_account": f"ACC-{i}"},
        )

    top = client.get("/analytics/summary").json()["top_accounts"]
    assert len(top) == 5
    assert top[0] == {"account": "ACC-HUB", "transaction_count": 7}
    assert [a["account"] for a in top[1:]] == ["ACC-0", "ACC-1", "ACC-2", "ACC-3"]


def test_analytics_summary_largest_transaction_tie_picks_earliest():
    first = client.post("/transactions", json=SAMPLE_TX).json()
    client.post("/transactions", json=SAMPLE_TX)

    body = client.get("/analytics/summary").json()
    assert body["largest_transaction"]["id"] == first["id"]


def test_analytics_summary_keeps_large_amounts_exact():
    huge = "1" + "0" * 40 + ".01"
    client.post("/transactions", json={**SAMPLE_TX, "amount": huge})
    client.post("/transactions", json={**SAMPLE_TX, "amount": "0.01"})

    body = client.get("/analytics/summary").json()
    assert body["total_volume"]["EUR"] == "1" + "0" * 40 + ".02"
    assert body["average_amount"] == "5" + "0" * 39 + ".01"


def test_analytics_summary_does_not_mutate_state():
    client.post("/transactions", json=SAMPLE_TX)
    client.post("/transactions", json={**SAMPLE_TX, "currency": "USD", "amount": "9.99"})
    before = client.get("/transactions").json()

    first = client.get("/analytics/summary")
    second = client.get("/analytics/summary")

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert client.get("/transactions").json() == before
    assert client.get("/health").json()["transactions"] == 2

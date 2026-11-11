from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import scheduling
from app.main import app, reset_store
from app.scheduler import JobResult, job
from app.scheduling import reset_scheduling_store

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


# --- QA coverage: /api/v2 scheduling slice ---------------------------------------------------


@pytest.fixture(autouse=True)
def clean_scheduling_state():
    reset_scheduling_store()
    yield
    reset_scheduling_store()


def _new_session(**overrides):
    payload = {"name": "Madrid TC-01", "capacity": 1, **overrides}
    response = client.post("/api/v2/sessions", json=payload)
    assert response.status_code == 201
    return response.json()["id"]


def _session_with_pending_offer():
    """capacity 1, booked by b0, w1 waitlisted then offered the seat b0 cancelled."""
    session_id = _new_session()
    booking = client.post(
        f"/api/v2/sessions/{session_id}/bookings", json={"candidate_id": "b0"}
    ).json()
    client.post(f"/api/v2/sessions/{session_id}/waitlist", json={"candidate_id": "w1"})
    client.post(f"/api/v2/bookings/{booking['id']}/cancel")
    offers = client.get("/api/v2/candidates/w1/bookings").json()["offers"]
    return session_id, offers[0]


def test_list_sessions_returns_created_sessions():
    assert client.get("/api/v2/sessions").json() == []
    first = _new_session(name="Morning")
    second = _new_session(name="Afternoon", capacity=3, accommodation_seats=1)

    response = client.get("/api/v2/sessions")

    assert response.status_code == 200
    body = response.json()
    assert [s["id"] for s in body] == [first, second]
    assert body[1]["seats_available"] == 3
    assert body[1]["accommodation_available"] == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "", "capacity": 1},
        {"name": "x", "capacity": -1},
        {"name": "x", "capacity": 1, "accommodation_seats": -1},
        {"name": "x", "capacity": 1, "status": "PAUSED"},
        {"capacity": 1},
        {"name": "x"},
    ],
)
def test_create_session_rejects_invalid_payload(payload):
    response = client.post("/api/v2/sessions", json=payload)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [{"capacity": -1}, {"capacity": 1, "accommodation_seats": -1}, {}],
)
def test_change_capacity_rejects_invalid_payload(payload):
    session_id = _new_session()
    response = client.patch(f"/api/v2/sessions/{session_id}/capacity", json=payload)
    assert response.status_code == 422


def test_list_session_bookings():
    session_id = _new_session(capacity=2)
    client.post(f"/api/v2/sessions/{session_id}/bookings", json={"candidate_id": "c1"})
    other = _new_session()
    client.post(f"/api/v2/sessions/{other}/bookings", json={"candidate_id": "c2"})

    response = client.get(f"/api/v2/sessions/{session_id}/bookings")

    assert response.status_code == 200
    assert [(b["candidate_id"], b["status"]) for b in response.json()] == [("c1", "BOOKED")]


def test_list_session_bookings_unknown_session_is_404():
    response = client.get("/api/v2/sessions/nope/bookings")
    assert response.status_code == 404
    assert response.json() == {"detail": "Session nope not found"}


def test_booking_a_closed_session_is_409():
    session_id = _new_session(status="CLOSED")
    response = client.post(f"/api/v2/sessions/{session_id}/bookings", json={"candidate_id": "c1"})
    assert response.status_code == 409
    assert "CLOSED" in response.json()["detail"]


@pytest.mark.parametrize("path", ["bookings", "waitlist"])
@pytest.mark.parametrize(
    "payload",
    [{"candidate_id": ""}, {"candidate_id": "c1", "accommodation": "X" * 21}, {}],
)
def test_candidate_request_validation(path, payload):
    session_id = _new_session()
    response = client.post(f"/api/v2/sessions/{session_id}/{path}", json=payload)
    assert response.status_code == 422


def test_join_waitlist_unknown_session_is_404():
    response = client.post("/api/v2/sessions/nope/waitlist", json={"candidate_id": "c1"})
    assert response.status_code == 404


def test_join_waitlist_with_free_seat_is_offered_immediately():
    session_id = _new_session()
    response = client.post(f"/api/v2/sessions/{session_id}/waitlist", json={"candidate_id": "w1"})
    assert response.status_code == 201
    body = response.json()
    assert body["position"] == 1
    assert body["offer"]["status"] == "PENDING"


def test_my_bookings_for_unknown_candidate_is_empty():
    response = client.get("/api/v2/candidates/nobody/bookings")
    assert response.status_code == 200
    assert response.json() == {
        "candidate_id": "nobody",
        "bookings": [],
        "offers": [],
        "waitlist": [],
    }


def test_get_offer_returns_pending_offer():
    session_id, offer = _session_with_pending_offer()
    response = client.get(f"/api/v2/offers/{offer['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == session_id
    assert body["candidate_id"] == "w1"
    assert body["status"] == "PENDING"
    assert body["booking_id"] is None


def test_decline_alias_under_bookings_path():
    session_id, offer = _session_with_pending_offer()
    response = client.post(f"/api/v2/bookings/offers/{offer['id']}/decline")
    assert response.status_code == 200
    assert response.json()["status"] == "DECLINED"
    assert client.get(f"/api/v2/sessions/{session_id}/waitlist").json() == []


@pytest.mark.parametrize("action", ["accept", "decline"])
def test_offer_alias_unknown_offer_is_404(action):
    response = client.post(f"/api/v2/bookings/offers/nope/{action}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Offer nope not found"}


def test_decline_twice_is_409():
    _, offer = _session_with_pending_offer()
    assert client.post(f"/api/v2/offers/{offer['id']}/decline").status_code == 200
    response = client.post(f"/api/v2/offers/{offer['id']}/decline")
    assert response.status_code == 409
    assert client.post(f"/api/v2/offers/{offer['id']}/accept").status_code == 409


def test_decline_after_expiry_is_409(monkeypatch):
    monkeypatch.setenv(scheduling.OFFER_TTL_ENV, "1")
    _, offer = _session_with_pending_offer()
    later = datetime.fromisoformat(offer["expires_at"]) + timedelta(seconds=1)
    monkeypatch.setattr(scheduling, "_now", lambda: later)

    response = client.post(f"/api/v2/offers/{offer['id']}/decline")

    assert response.status_code == 409
    assert "expired" in response.json()["detail"]
    assert client.get(f"/api/v2/offers/{offer['id']}").json()["status"] == "EXPIRED"


def test_accept_after_expiry_over_http_is_409(monkeypatch):
    _, offer = _session_with_pending_offer()
    later = datetime.fromisoformat(offer["expires_at"]) + timedelta(seconds=1)
    monkeypatch.setattr(scheduling, "_now", lambda: later)

    response = client.post(f"/api/v2/offers/{offer['id']}/accept")

    assert response.status_code == 409
    assert "expired" in response.json()["detail"]


def test_outbox_pending_only_filters_relayed_events():
    _session_with_pending_offer()
    total = len(client.get("/api/v2/outbox").json())
    assert len(client.get("/api/v2/outbox", params={"pending_only": "true"}).json()) == total

    client.post("/api/v2/outbox/relay")

    assert client.get("/api/v2/outbox", params={"pending_only": "true"}).json() == []
    assert len(client.get("/api/v2/outbox").json()) == total
    assert client.post("/api/v2/outbox/relay").json() == {"relayed": 0}


def test_outbox_rejects_invalid_pending_only():
    response = client.get("/api/v2/outbox", params={"pending_only": "maybe"})
    assert response.status_code == 422


def test_reconciliation_with_no_sessions():
    response = client.get("/api/v2/reconciliation")
    assert response.status_code == 200
    assert response.json() == {
        "sessions_checked": 0,
        "pending_events": 0,
        "mismatches": 0,
        "details": [],
    }


@pytest.mark.parametrize("name", ["waitlist-offer-expiry", "scheduling-outbox-relay"])
def test_run_scheduling_jobs_via_ops_endpoint(name):
    _session_with_pending_offer()
    response = client.post(f"/ops/jobs/{name}/run")
    assert response.status_code == 200
    assert response.json()["job"] == name


def test_outbox_relay_job_dry_run_does_not_relay():
    _session_with_pending_offer()
    pending = len(client.get("/api/v2/outbox", params={"pending_only": "true"}).json())

    response = client.post("/ops/jobs/scheduling-outbox-relay/run", params={"dry_run": "true"})

    assert response.json()["processed"] == pending
    assert response.json()["notes"] == [f"would relay {pending} event(s)"]
    still_pending = client.get("/api/v2/outbox", params={"pending_only": "true"}).json()
    assert len(still_pending) == pending


@pytest.mark.xfail(
    strict=True,
    reason="accept_offer does not check for an existing BOOKED booking, so a candidate "
    "holding an offer can book directly and then accept, ending up booked twice",
)
def test_candidate_with_pending_offer_cannot_end_up_double_booked():
    session_id = _new_session()
    client.post(f"/api/v2/sessions/{session_id}/bookings", json={"candidate_id": "b0"})
    client.post(f"/api/v2/sessions/{session_id}/waitlist", json={"candidate_id": "w1"})
    client.patch(f"/api/v2/sessions/{session_id}/capacity", json={"capacity": 3})
    offer = client.get("/api/v2/candidates/w1/bookings").json()["offers"][0]

    client.post(f"/api/v2/sessions/{session_id}/bookings", json={"candidate_id": "w1"})
    client.post(f"/api/v2/offers/{offer['id']}/accept")

    bookings = client.get(f"/api/v2/sessions/{session_id}/bookings").json()
    booked_w1 = [b for b in bookings if b["candidate_id"] == "w1" and b["status"] == "BOOKED"]
    assert len(booked_w1) == 1

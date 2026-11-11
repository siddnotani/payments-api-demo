import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import scheduling
from app.main import app
from app.scheduler import JobContext

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_scheduling_store():
    scheduling.reset_scheduling_store()
    yield
    scheduling.reset_scheduling_store()


def make_session(capacity=2, accommodation_seats=0, status="OPEN"):
    response = client.post(
        "/api/v2/sessions",
        json={
            "name": "Madrid TC-01",
            "capacity": capacity,
            "accommodation_seats": accommodation_seats,
            "status": status,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def book(session_id, candidate_id, accommodation=None):
    return client.post(
        f"/api/v2/sessions/{session_id}/bookings",
        json={"candidate_id": candidate_id, "accommodation": accommodation},
    )


def join(session_id, candidate_id, accommodation=None):
    response = client.post(
        f"/api/v2/sessions/{session_id}/waitlist",
        json={"candidate_id": candidate_id, "accommodation": accommodation},
    )
    assert response.status_code == 201
    return response.json()


def session_view(session_id):
    return client.get(f"/api/v2/sessions/{session_id}").json()


def waitlist(session_id):
    return client.get(f"/api/v2/sessions/{session_id}/waitlist").json()


def cancel(booking_id):
    return client.post(f"/api/v2/bookings/{booking_id}/cancel")


def full_session_with_waitlist(capacity=2, accommodation_seats=0, waitlisted=None):
    """Book every seat (booked-0..n) and waitlist the given candidates in order."""
    session_id = make_session(capacity=capacity, accommodation_seats=accommodation_seats)
    bookings = [book(session_id, f"booked-{i}").json() for i in range(capacity)]
    for candidate_id, accommodation in waitlisted or [("w1", None), ("w2", None), ("w3", None)]:
        join(session_id, candidate_id, accommodation)
    assert session_view(session_id)["seats_available"] == 0
    return session_id, bookings


def pending_offers(candidate_id):
    offers = client.get(f"/api/v2/candidates/{candidate_id}/bookings").json()["offers"]
    return [o for o in offers if o["status"] == "PENDING"]


# --- session and booking basics ------------------------------------------------------------


def test_create_session_reports_seat_availability():
    session_id = make_session(capacity=3, accommodation_seats=1)
    view = session_view(session_id)
    assert view["seats_available"] == 3
    assert view["standard_available"] == 2
    assert view["accommodation_available"] == 1
    assert view["seats_held"] == 0


def test_create_session_rejects_more_accommodation_seats_than_capacity():
    response = client.post(
        "/api/v2/sessions", json={"name": "x", "capacity": 1, "accommodation_seats": 2}
    )
    assert response.status_code == 422


def test_unknown_session_is_404():
    assert client.get("/api/v2/sessions/nope").status_code == 404
    assert client.get("/api/v2/sessions/nope/waitlist").status_code == 404
    assert book("nope", "c1").status_code == 404


def test_booking_a_full_session_is_409():
    session_id = make_session(capacity=1)
    assert book(session_id, "c1").status_code == 201
    response = book(session_id, "c2")
    assert response.status_code == 409
    assert "waitlist" in response.json()["detail"]


def test_double_booking_and_double_waitlisting_are_409():
    session_id = make_session(capacity=1)
    assert book(session_id, "c1").status_code == 201
    assert book(session_id, "c1").status_code == 409
    join(session_id, "c2")
    again = client.post(f"/api/v2/sessions/{session_id}/waitlist", json={"candidate_id": "c2"})
    assert again.status_code == 409
    booked = client.post(f"/api/v2/sessions/{session_id}/waitlist", json={"candidate_id": "c1"})
    assert booked.status_code == 409


def test_cancel_unknown_or_cancelled_booking():
    assert cancel("nope").status_code == 404
    session_id = make_session(capacity=1)
    booking = book(session_id, "c1").json()
    assert cancel(booking["id"]).status_code == 200
    assert cancel(booking["id"]).status_code == 409


def test_accommodation_candidate_cannot_book_standard_seat():
    session_id = make_session(capacity=1, accommodation_seats=0)
    assert book(session_id, "c1", "ET25").status_code == 409


def test_booking_rejects_blank_candidate():
    session_id = make_session()
    response = client.post(f"/api/v2/sessions/{session_id}/bookings", json={"candidate_id": ""})
    assert response.status_code == 422


# --- AC1: cancel offers the seat to position 1 and holds it --------------------------------


def test_cancel_offers_freed_seat_to_position_one_and_holds_it():
    session_id, bookings = full_session_with_waitlist()

    assert cancel(bookings[0]["id"]).status_code == 200

    entries = waitlist(session_id)
    assert [e["candidate_id"] for e in entries] == ["w1", "w2", "w3"]
    assert entries[0]["offer"]["status"] == "PENDING"
    assert entries[1]["offer"] is None and entries[2]["offer"] is None
    view = session_view(session_id)
    assert view["seats_available"] == 0
    assert view["seats_held"] == 1
    assert book(session_id, "walk-in").status_code == 409


def test_offer_expires_after_configured_ttl(monkeypatch):
    monkeypatch.setenv(scheduling.OFFER_TTL_ENV, "3600")
    session_id, bookings = full_session_with_waitlist()
    cancel(bookings[0]["id"])
    offer = waitlist(session_id)[0]["offer"]
    created = datetime.fromisoformat(offer["created_at"])
    assert datetime.fromisoformat(offer["expires_at"]) - created == timedelta(hours=1)


def test_offer_ttl_defaults_to_24_hours(monkeypatch):
    monkeypatch.delenv(scheduling.OFFER_TTL_ENV, raising=False)
    assert scheduling.offer_ttl() == timedelta(hours=24)


def test_offer_ttl_rejects_non_positive(monkeypatch):
    monkeypatch.setenv(scheduling.OFFER_TTL_ENV, "0")
    with pytest.raises(ValueError):
        scheduling.offer_ttl()


def test_closed_session_does_not_auto_offer():
    session_id = make_session(capacity=1)
    booking = book(session_id, "c1").json()
    join(session_id, "w1")
    scheduling._sessions[session_id].status = scheduling.SessionStatus.CLOSED
    cancel(booking["id"])
    assert waitlist(session_id)[0]["offer"] is None


# --- AC2: accept -----------------------------------------------------------------------------


def test_accept_books_candidate_and_shifts_positions():
    session_id, bookings = full_session_with_waitlist()
    cancel(bookings[0]["id"])
    offer = pending_offers("w1")[0]

    response = client.post(f"/api/v2/offers/{offer['id']}/accept")

    assert response.status_code == 200
    booking = response.json()
    assert booking["status"] == "BOOKED"
    assert booking["candidate_id"] == "w1"
    assert booking["offer_id"] == offer["id"]
    entries = waitlist(session_id)
    assert [(e["candidate_id"], e["position"]) for e in entries] == [("w2", 1), ("w3", 2)]
    view = session_view(session_id)
    assert view["booked"] == 2 and view["seats_held"] == 0 and view["seats_available"] == 0
    assert client.get(f"/api/v2/offers/{offer['id']}").json()["status"] == "ACCEPTED"


def test_accept_is_projected_into_legacy_tables_by_relay():
    session_id, bookings = full_session_with_waitlist()
    cancel(bookings[0]["id"])
    offer = pending_offers("w1")[0]
    booking = client.post(f"/api/v2/offers/{offer['id']}/accept").json()

    assert client.post("/api/v2/outbox/relay").json()["relayed"] > 0

    legacy_booking = scheduling._legacy_bookings[booking["id"]]
    assert legacy_booking == {"session_id": session_id, "candidate_id": "w1", "status": "BOOKED"}
    assert scheduling._legacy_bookings[bookings[0]["id"]]["status"] == "CANCELLED"
    legacy_waitlist = sorted(
        (r["position"], r["candidate_id"]) for r in scheduling._legacy_waitlist.values()
    )
    assert legacy_waitlist == [(1, "w2"), (2, "w3")]
    types = [e["type"] for e in client.get("/api/v2/outbox").json()]
    assert "SeatOffered" in types and "SeatOfferAccepted" in types


def test_accept_alias_under_bookings_path():
    session_id, bookings = full_session_with_waitlist()
    cancel(bookings[0]["id"])
    offer = pending_offers("w1")[0]
    response = client.post(f"/api/v2/bookings/offers/{offer['id']}/accept")
    assert response.status_code == 200


def test_accept_unknown_offer_is_404():
    assert client.post("/api/v2/offers/nope/accept").status_code == 404
    assert client.post("/api/v2/offers/nope/decline").status_code == 404
    assert client.get("/api/v2/offers/nope").status_code == 404


def test_accept_twice_is_409():
    session_id, bookings = full_session_with_waitlist()
    cancel(bookings[0]["id"])
    offer = pending_offers("w1")[0]
    assert client.post(f"/api/v2/offers/{offer['id']}/accept").status_code == 200
    assert client.post(f"/api/v2/offers/{offer['id']}/accept").status_code == 409
    assert client.post(f"/api/v2/offers/{offer['id']}/decline").status_code == 409


def test_accept_after_expiry_is_409_and_moves_on():
    session_id, bookings = full_session_with_waitlist()
    cancel(bookings[0]["id"])
    offer = pending_offers("w1")[0]
    later = datetime.fromisoformat(offer["expires_at"]) + timedelta(seconds=1)

    with pytest.raises(scheduling.HTTPException) as exc:
        scheduling.accept_offer(offer["id"], now=later)

    assert exc.value.status_code == 409
    assert scheduling._offers[offer["id"]].status == scheduling.OfferStatus.EXPIRED
    assert len(pending_offers("w2")) == 1


# --- AC3: decline / expiry moves on; nobody left frees the seat ----------------------------


def test_decline_offers_seat_to_next_candidate():
    session_id, bookings = full_session_with_waitlist()
    cancel(bookings[0]["id"])
    offer = pending_offers("w1")[0]

    response = client.post(f"/api/v2/offers/{offer['id']}/decline")

    assert response.status_code == 200
    assert response.json()["status"] == "DECLINED"
    entries = waitlist(session_id)
    assert [e["candidate_id"] for e in entries] == ["w2", "w3"]
    assert entries[0]["offer"]["status"] == "PENDING"
    assert session_view(session_id)["seats_available"] == 0


def test_expiry_job_offers_seat_to_next_candidate():
    session_id, bookings = full_session_with_waitlist()
    cancel(bookings[0]["id"])
    offer = pending_offers("w1")[0]
    later = datetime.fromisoformat(offer["expires_at"]) + timedelta(minutes=1)

    from app.jobs.waitlist_offers import waitlist_offer_expiry

    dry = waitlist_offer_expiry(JobContext(now=later, dry_run=True))
    assert dry.processed == 1
    assert pending_offers("w1")

    result = waitlist_offer_expiry(JobContext(now=later))
    assert result.processed == 1
    assert client.get(f"/api/v2/offers/{offer['id']}").json()["status"] == "EXPIRED"
    assert [e["candidate_id"] for e in waitlist(session_id)] == ["w2", "w3"]
    assert len(pending_offers("w2")) == 1


def test_expiry_job_ignores_offers_before_expiry():
    session_id, bookings = full_session_with_waitlist()
    cancel(bookings[0]["id"])
    assert scheduling.expire_offers(datetime.now(UTC)) == 0
    assert len(pending_offers("w1")) == 1


def test_seat_becomes_available_when_nobody_is_left():
    session_id, bookings = full_session_with_waitlist(waitlisted=[("w1", None)])
    cancel(bookings[0]["id"])
    offer = pending_offers("w1")[0]
    client.post(f"/api/v2/offers/{offer['id']}/decline")

    assert waitlist(session_id) == []
    view = session_view(session_id)
    assert view["seats_held"] == 0
    assert view["seats_available"] == 1
    assert book(session_id, "walk-in").status_code == 201


def test_expiry_jobs_are_registered():
    names = {j["name"] for j in client.get("/ops/jobs").json()}
    assert {"waitlist-offer-expiry", "scheduling-outbox-relay"} <= names


# --- AC4: accommodation needs ---------------------------------------------------------------


def test_accommodation_candidate_is_skipped_for_standard_seat_and_kept_in_place():
    session_id, bookings = full_session_with_waitlist(
        capacity=2,
        accommodation_seats=1,
        waitlisted=[("needs-et25", "ET25"), ("w2", None), ("w3", None)],
    )
    standard = next(b for b in bookings if b["seat_type"] == "STANDARD")

    cancel(standard["id"])

    entries = waitlist(session_id)
    assert [(e["candidate_id"], e["position"]) for e in entries] == [
        ("needs-et25", 1),
        ("w2", 2),
        ("w3", 3),
    ]
    assert entries[0]["offer"] is None
    assert entries[1]["offer"]["status"] == "PENDING"
    assert entries[1]["offer"]["seat_type"] == "STANDARD"


def test_freed_accommodation_seat_goes_to_accommodation_candidate_in_position_order():
    session_id, bookings = full_session_with_waitlist(
        capacity=2,
        accommodation_seats=1,
        waitlisted=[("needs-et25", "ET25"), ("w2", None)],
    )
    accommodation = next(b for b in bookings if b["seat_type"] == "ACCOMMODATION")
    cancel(accommodation["id"])
    offer = waitlist(session_id)[0]["offer"]
    assert offer["candidate_id"] == "needs-et25"
    assert offer["seat_type"] == "ACCOMMODATION"


# --- AC5: multiple seats and concurrency ------------------------------------------------------


def test_capacity_increase_makes_offers_in_position_order():
    session_id, _ = full_session_with_waitlist()
    response = client.patch(f"/api/v2/sessions/{session_id}/capacity", json={"capacity": 4})
    assert response.status_code == 200
    entries = waitlist(session_id)
    assert [e["offer"] is not None for e in entries] == [True, True, False]
    assert response.json()["seats_held"] == 2
    assert response.json()["seats_available"] == 0


def test_capacity_cannot_drop_below_booked_and_held_seats():
    session_id, bookings = full_session_with_waitlist()
    cancel(bookings[0]["id"])
    response = client.patch(f"/api/v2/sessions/{session_id}/capacity", json={"capacity": 1})
    assert response.status_code == 409
    invalid = client.patch(
        f"/api/v2/sessions/{session_id}/capacity",
        json={"capacity": 2, "accommodation_seats": 3},
    )
    assert invalid.status_code == 422
    missing = client.patch("/api/v2/sessions/nope/capacity", json={"capacity": 1})
    assert missing.status_code == 404


def test_two_seats_freed_at_once_get_two_offers_in_position_order():
    session_id, bookings = full_session_with_waitlist()
    scheduling._bookings[bookings[0]["id"]].status = scheduling.BookingStatus.CANCELLED
    scheduling._bookings[bookings[1]["id"]].status = scheduling.BookingStatus.CANCELLED

    made = scheduling.offer_policy.on_seat_freed(session_id)

    assert [o.candidate_id for o in made] == ["w1", "w2"]


def test_concurrent_cancels_never_double_offer():
    capacity = 10
    waitlisted = [(f"w{i}", None) for i in range(1, 16)]
    session_id, bookings = full_session_with_waitlist(capacity=capacity, waitlisted=waitlisted)
    barrier = threading.Barrier(capacity)

    def cancel_one(booking_id):
        barrier.wait()
        scheduling.cancel_booking(booking_id)
        scheduling.offer_policy.on_seat_freed(session_id)

    threads = [threading.Thread(target=cancel_one, args=(b["id"],)) for b in bookings]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    pending = [o for o in scheduling._offers.values() if o.status == "PENDING"]
    assert len(pending) == capacity
    assert len({o.waitlist_entry_id for o in pending}) == capacity
    assert sorted(o.candidate_id for o in pending) == sorted(f"w{i}" for i in range(1, 11))
    assert session_view(session_id)["seats_available"] == 0


def test_concurrent_accepts_of_one_offer_book_once():
    session_id, bookings = full_session_with_waitlist()
    cancel(bookings[0]["id"])
    offer_id = pending_offers("w1")[0]["id"]
    barrier = threading.Barrier(8)
    outcomes = []

    def accept():
        barrier.wait()
        try:
            scheduling.accept_offer(offer_id)
            outcomes.append("ok")
        except scheduling.HTTPException as exc:
            outcomes.append(exc.status_code)

    threads = [threading.Thread(target=accept) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert outcomes.count("ok") == 1
    assert outcomes.count(409) == 7
    booked = [b for b in scheduling._bookings.values() if b.candidate_id == "w1"]
    assert len(booked) == 1


# --- AC6: reconciliation ----------------------------------------------------------------------


def test_reconciliation_reports_zero_mismatches_after_offer_cycle():
    session_id, bookings = full_session_with_waitlist(
        capacity=2,
        accommodation_seats=1,
        waitlisted=[("needs-et25", "ET25"), ("w2", None), ("w3", None), ("w4", None)],
    )
    client.post("/api/v2/outbox/relay")
    assert client.get("/api/v2/reconciliation").json()["mismatches"] == 0

    standard = next(b for b in bookings if b["seat_type"] == "STANDARD")
    cancel(standard["id"])
    declined = pending_offers("w2")[0]
    client.post(f"/api/v2/offers/{declined['id']}/decline")
    expired = pending_offers("w3")[0]
    later = datetime.fromisoformat(expired["expires_at"]) + timedelta(seconds=1)
    scheduling.expire_offers(later)
    accepted = pending_offers("w4")[0]
    client.post(f"/api/v2/offers/{accepted['id']}/accept")

    before = client.get("/api/v2/reconciliation").json()
    assert before["pending_events"] > 0
    assert before["mismatches"] > 0

    from app.jobs.waitlist_offers import scheduling_outbox_relay

    assert scheduling_outbox_relay(JobContext(now=datetime.now(UTC))).processed > 0
    report = client.get("/api/v2/reconciliation").json()
    assert report == {"sessions_checked": 1, "pending_events": 0, "mismatches": 0, "details": []}
    assert [e["candidate_id"] for e in waitlist(session_id)] == ["needs-et25"]


# --- My bookings / UI ---------------------------------------------------------------------------


def test_my_bookings_lists_offers_bookings_and_waitlist():
    session_id, bookings = full_session_with_waitlist()
    cancel(bookings[0]["id"])
    body = client.get("/api/v2/candidates/w1/bookings").json()
    assert body["candidate_id"] == "w1"
    assert [o["status"] for o in body["offers"]] == ["PENDING"]
    assert body["bookings"] == []
    assert [(w["session_id"], w["position"]) for w in body["waitlist"]] == [(session_id, 1)]


def test_app_page_is_served():
    response = client.get("/app")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "My bookings" in response.text
    assert "waitlist drawer" in response.text

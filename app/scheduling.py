"""Test-center scheduling slice: sessions, bookings, waitlist and automatic seat offers.

State lives in memory, like the transactions store. Every write appends an event to an
in-memory outbox; :func:`relay_outbox` projects those events into the legacy
``Booking`` / ``Waitlist`` read model and :func:`reconcile` compares both sides.

When a seat frees up in an OPEN session, :class:`WaitlistOfferPolicy` offers it to the
lowest-position waitlist entry whose accommodation needs fit the seat and holds the seat
until the offer is accepted, declined or expires (see docs/adr/0001-waitlist-auto-offer.md).
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

OFFER_TTL_ENV = "SCHEDULING_WAITLIST_OFFER_TTL_SECONDS"
DEFAULT_OFFER_TTL = timedelta(hours=24)

router = APIRouter(prefix="/api/v2", tags=["scheduling"])


class SessionStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SeatType(StrEnum):
    STANDARD = "STANDARD"
    ACCOMMODATION = "ACCOMMODATION"


class BookingStatus(StrEnum):
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"


class OfferStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class SessionCreate(BaseModel):
    name: str = Field(..., min_length=1, examples=["Madrid TC-01 morning"])
    capacity: int = Field(..., ge=0, description="Total seats, accommodation seats included.")
    accommodation_seats: int = Field(
        default=0, ge=0, description="Seats that support accommodations such as ET25."
    )
    status: SessionStatus = SessionStatus.OPEN


class Session(SessionCreate):
    id: str
    created_at: datetime


class SessionView(Session):
    booked: int
    seats_held: int
    seats_available: int
    standard_available: int
    accommodation_available: int
    waitlist_length: int


class CapacityChange(BaseModel):
    capacity: int = Field(..., ge=0)
    accommodation_seats: int | None = Field(default=None, ge=0)


class CandidateRequest(BaseModel):
    candidate_id: str = Field(..., min_length=1, examples=["cand-001"])
    accommodation: str | None = Field(default=None, max_length=20, examples=[None, "ET25"])


class Booking(BaseModel):
    id: str
    session_id: str
    candidate_id: str
    accommodation: str | None
    seat_type: SeatType
    status: BookingStatus
    created_at: datetime
    offer_id: str | None = None


class SeatOffer(BaseModel):
    id: str
    session_id: str
    waitlist_entry_id: str
    candidate_id: str
    seat_type: SeatType
    status: OfferStatus
    created_at: datetime
    expires_at: datetime
    resolved_at: datetime | None = None
    booking_id: str | None = None


class WaitlistEntry(BaseModel):
    id: str
    session_id: str
    candidate_id: str
    accommodation: str | None
    joined_at: datetime


class WaitlistEntryView(WaitlistEntry):
    position: int
    offer: SeatOffer | None = None


class CandidateBookings(BaseModel):
    candidate_id: str
    bookings: list[Booking]
    offers: list[SeatOffer]
    waitlist: list[WaitlistEntryView]


class OutboxEvent(BaseModel):
    id: str
    type: str
    session_id: str
    payload: dict[str, Any]
    created_at: datetime
    relayed: bool = False


class RelayResult(BaseModel):
    relayed: int


class ReconciliationReport(BaseModel):
    sessions_checked: int
    pending_events: int
    mismatches: int
    details: list[str]


_lock = threading.RLock()
_sessions: dict[str, Session] = {}
_bookings: dict[str, Booking] = {}
_waitlist: dict[str, WaitlistEntry] = {}  # insertion order == waitlist order
_offers: dict[str, SeatOffer] = {}
_outbox: list[OutboxEvent] = []
_legacy_bookings: dict[str, dict[str, str]] = {}
_legacy_waitlist: dict[str, dict[str, Any]] = {}


def reset_scheduling_store() -> None:
    """Clear all scheduling state, including the outbox and legacy projection (tests)."""
    with _lock:
        for store in (_sessions, _bookings, _waitlist, _offers, _legacy_bookings, _legacy_waitlist):
            store.clear()
        _outbox.clear()


def offer_ttl() -> timedelta:
    """``scheduling.waitlist.offer-ttl``: seconds from the env, 24h by default."""
    raw = os.environ.get(OFFER_TTL_ENV)
    if raw is None:
        return DEFAULT_OFFER_TTL
    seconds = int(raw)
    if seconds <= 0:
        raise ValueError(f"{OFFER_TTL_ENV} must be a positive number of seconds")
    return timedelta(seconds=seconds)


def _now() -> datetime:
    return datetime.now(UTC)


def _not_found(kind: str, key: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{kind} {key} not found")


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _emit(event_type: str, session_id: str, **payload: Any) -> None:
    _outbox.append(
        OutboxEvent(
            id=str(uuid4()),
            type=event_type,
            session_id=session_id,
            payload=payload,
            created_at=_now(),
        )
    )


def _get_session(session_id: str) -> Session:
    session = _sessions.get(session_id)
    if session is None:
        raise _not_found("Session", session_id)
    return session


def _get_offer(offer_id: str) -> SeatOffer:
    offer = _offers.get(offer_id)
    if offer is None:
        raise _not_found("Offer", offer_id)
    return offer


def _seat_capacity(session: Session) -> dict[SeatType, int]:
    return {
        SeatType.STANDARD: session.capacity - session.accommodation_seats,
        SeatType.ACCOMMODATION: session.accommodation_seats,
    }


def _seats_in_use(session_id: str) -> tuple[dict[SeatType, int], dict[SeatType, int]]:
    booked = dict.fromkeys(SeatType, 0)
    held = dict.fromkeys(SeatType, 0)
    for b in _bookings.values():
        if b.session_id == session_id and b.status == BookingStatus.BOOKED:
            booked[b.seat_type] += 1
    for o in _offers.values():
        if o.session_id == session_id and o.status == OfferStatus.PENDING:
            held[o.seat_type] += 1
    return booked, held


def _free_seats(session: Session) -> dict[SeatType, int]:
    booked, held = _seats_in_use(session.id)
    cap = _seat_capacity(session)
    return {t: max(cap[t] - booked[t] - held[t], 0) for t in SeatType}


def _fitting_seat(accommodation: str | None, free: dict[SeatType, int]) -> SeatType | None:
    """Accommodation candidates need an accommodation seat; others prefer a standard one."""
    if accommodation:
        return SeatType.ACCOMMODATION if free[SeatType.ACCOMMODATION] > 0 else None
    for seat_type in (SeatType.STANDARD, SeatType.ACCOMMODATION):
        if free[seat_type] > 0:
            return seat_type
    return None


def _session_waitlist(session_id: str) -> list[WaitlistEntry]:
    return [e for e in _waitlist.values() if e.session_id == session_id]


def _pending_offer_for(entry_id: str) -> SeatOffer | None:
    return next(
        (
            o
            for o in _offers.values()
            if o.waitlist_entry_id == entry_id and o.status == OfferStatus.PENDING
        ),
        None,
    )


def _session_view(session: Session) -> SessionView:
    booked, held = _seats_in_use(session.id)
    free = _free_seats(session)
    return SessionView(
        **session.model_dump(),
        booked=sum(booked.values()),
        seats_held=sum(held.values()),
        seats_available=sum(free.values()),
        standard_available=free[SeatType.STANDARD],
        accommodation_available=free[SeatType.ACCOMMODATION],
        waitlist_length=len(_session_waitlist(session.id)),
    )


def _waitlist_view(session_id: str) -> list[WaitlistEntryView]:
    return [
        WaitlistEntryView(**e.model_dump(), position=i, offer=_pending_offer_for(e.id))
        for i, e in enumerate(_session_waitlist(session_id), start=1)
    ]


class WaitlistOfferPolicy:
    """Offers every free seat of an OPEN session to the next eligible waitlist entry."""

    def on_seat_freed(self, session_id: str, now: datetime | None = None) -> list[SeatOffer]:
        now = now or _now()
        made: list[SeatOffer] = []
        with _lock:
            session = _sessions[session_id]
            if session.status != SessionStatus.OPEN:
                return made
            while (match := self._next_candidate(session)) is not None:
                entry, seat_type = match
                offer = SeatOffer(
                    id=str(uuid4()),
                    session_id=session_id,
                    waitlist_entry_id=entry.id,
                    candidate_id=entry.candidate_id,
                    seat_type=seat_type,
                    status=OfferStatus.PENDING,
                    created_at=now,
                    expires_at=now + offer_ttl(),
                )
                _offers[offer.id] = offer
                _emit(
                    "SeatOffered",
                    session_id,
                    offer_id=offer.id,
                    waitlist_entry_id=entry.id,
                    candidate_id=entry.candidate_id,
                    seat_type=seat_type.value,
                    expires_at=offer.expires_at.isoformat(),
                )
                made.append(offer)
        return made

    @staticmethod
    def _next_candidate(session: Session) -> tuple[WaitlistEntry, SeatType] | None:
        free = _free_seats(session)
        for entry in _session_waitlist(session.id):
            if _pending_offer_for(entry.id) is not None:
                continue
            seat_type = _fitting_seat(entry.accommodation, free)
            if seat_type is not None:
                return entry, seat_type
        return None


offer_policy = WaitlistOfferPolicy()


def _close_offer(offer: SeatOffer, outcome: OfferStatus, event_type: str, now: datetime) -> None:
    offer.status = outcome
    offer.resolved_at = now
    _waitlist.pop(offer.waitlist_entry_id, None)
    _emit(
        event_type,
        offer.session_id,
        offer_id=offer.id,
        waitlist_entry_id=offer.waitlist_entry_id,
        candidate_id=offer.candidate_id,
    )


def _require_pending(offer: SeatOffer, now: datetime) -> None:
    if offer.status != OfferStatus.PENDING:
        raise _conflict(f"Offer {offer.id} is {offer.status.value}")
    if now >= offer.expires_at:
        _close_offer(offer, OfferStatus.EXPIRED, "SeatOfferExpired", now)
        offer_policy.on_seat_freed(offer.session_id, now)
        raise _conflict(f"Offer {offer.id} has expired")


def accept_offer(offer_id: str, now: datetime | None = None) -> Booking:
    now = now or _now()
    with _lock:
        offer = _get_offer(offer_id)
        _require_pending(offer, now)
        entry = _waitlist[offer.waitlist_entry_id]
        booking = Booking(
            id=str(uuid4()),
            session_id=offer.session_id,
            candidate_id=offer.candidate_id,
            accommodation=entry.accommodation,
            seat_type=offer.seat_type,
            status=BookingStatus.BOOKED,
            created_at=now,
            offer_id=offer.id,
        )
        _bookings[booking.id] = booking
        offer.booking_id = booking.id
        offer.status = OfferStatus.ACCEPTED
        offer.resolved_at = now
        _waitlist.pop(entry.id)
        _emit(
            "SeatOfferAccepted",
            offer.session_id,
            offer_id=offer.id,
            waitlist_entry_id=entry.id,
            booking_id=booking.id,
            candidate_id=offer.candidate_id,
        )
        return booking


def decline_offer(offer_id: str, now: datetime | None = None) -> SeatOffer:
    now = now or _now()
    with _lock:
        offer = _get_offer(offer_id)
        _require_pending(offer, now)
        _close_offer(offer, OfferStatus.DECLINED, "SeatOfferDeclined", now)
        offer_policy.on_seat_freed(offer.session_id, now)
        return offer


def expire_offers(now: datetime | None = None, *, dry_run: bool = False) -> int:
    """Expire overdue PENDING offers and offer the seats to the next candidates."""
    now = now or _now()
    with _lock:
        overdue = [
            o for o in _offers.values() if o.status == OfferStatus.PENDING and now >= o.expires_at
        ]
        if dry_run:
            return len(overdue)
        for offer in overdue:
            _close_offer(offer, OfferStatus.EXPIRED, "SeatOfferExpired", now)
        for session_id in dict.fromkeys(o.session_id for o in overdue):
            offer_policy.on_seat_freed(session_id, now)
        return len(overdue)


def cancel_booking(booking_id: str) -> Booking:
    with _lock:
        booking = _bookings.get(booking_id)
        if booking is None:
            raise _not_found("Booking", booking_id)
        if booking.status == BookingStatus.CANCELLED:
            raise _conflict(f"Booking {booking_id} is already cancelled")
        booking.status = BookingStatus.CANCELLED
        _emit("BookingCancelled", booking.session_id, booking_id=booking.id)
        offer_policy.on_seat_freed(booking.session_id)
        return booking


def _has_active_booking(session_id: str, candidate_id: str) -> bool:
    return any(
        b.session_id == session_id
        and b.candidate_id == candidate_id
        and b.status == BookingStatus.BOOKED
        for b in _bookings.values()
    )


def _is_waitlisted(session_id: str, candidate_id: str) -> bool:
    return any(e.candidate_id == candidate_id for e in _session_waitlist(session_id))


# --- outbox relay and reconciliation -------------------------------------------------------


def _renumber_legacy_waitlist(session_id: str) -> None:
    rows = sorted(
        (r for r in _legacy_waitlist.values() if r["session_id"] == session_id),
        key=lambda r: r["position"],
    )
    for i, row in enumerate(rows, start=1):
        row["position"] = i


def _project(event: OutboxEvent) -> None:
    p = event.payload
    if event.type == "BookingCreated" or event.type == "SeatOfferAccepted":
        booking = _bookings[p["booking_id"]]
        _legacy_bookings[booking.id] = {
            "session_id": booking.session_id,
            "candidate_id": booking.candidate_id,
            "status": BookingStatus.BOOKED.value,
        }
    if event.type == "BookingCancelled":
        _legacy_bookings[p["booking_id"]]["status"] = BookingStatus.CANCELLED.value
    if event.type == "WaitlistJoined":
        positions = [
            r["position"] for r in _legacy_waitlist.values() if r["session_id"] == event.session_id
        ]
        _legacy_waitlist[p["waitlist_entry_id"]] = {
            "session_id": event.session_id,
            "candidate_id": p["candidate_id"],
            "position": max(positions, default=0) + 1,
        }
    if event.type in {"SeatOfferAccepted", "SeatOfferDeclined", "SeatOfferExpired"}:
        _legacy_waitlist.pop(p["waitlist_entry_id"], None)
        _renumber_legacy_waitlist(event.session_id)


def relay_outbox(*, dry_run: bool = False) -> int:
    """Project unrelayed outbox events into the legacy Booking / Waitlist read model."""
    with _lock:
        pending = [e for e in _outbox if not e.relayed]
        if dry_run:
            return len(pending)
        for event in pending:
            _project(event)
            event.relayed = True
        return len(pending)


def reconcile() -> ReconciliationReport:
    """Compare modern bookings / waitlist with the legacy projection."""
    with _lock:
        details: list[str] = []
        for session_id in _sessions:
            modern_booked = {
                (b.id, b.candidate_id)
                for b in _bookings.values()
                if b.session_id == session_id and b.status == BookingStatus.BOOKED
            }
            legacy_booked = {
                (bid, row["candidate_id"])
                for bid, row in _legacy_bookings.items()
                if row["session_id"] == session_id and row["status"] == BookingStatus.BOOKED
            }
            modern_wait = {(e.id, e.candidate_id, e.position) for e in _waitlist_view(session_id)}
            legacy_wait = {
                (eid, row["candidate_id"], row["position"])
                for eid, row in _legacy_waitlist.items()
                if row["session_id"] == session_id
            }
            for item in sorted(modern_booked ^ legacy_booked):
                details.append(f"session {session_id}: booking mismatch {item}")
            for item in sorted(modern_wait ^ legacy_wait):
                details.append(f"session {session_id}: waitlist mismatch {item}")
        return ReconciliationReport(
            sessions_checked=len(_sessions),
            pending_events=sum(1 for e in _outbox if not e.relayed),
            mismatches=len(details),
            details=details,
        )


# --- HTTP API --------------------------------------------------------------------------------


@router.post("/sessions", response_model=SessionView, status_code=status.HTTP_201_CREATED)
def create_session(payload: SessionCreate) -> SessionView:
    if payload.accommodation_seats > payload.capacity:
        raise HTTPException(status_code=422, detail="accommodation_seats cannot exceed capacity")
    with _lock:
        session = Session(id=str(uuid4()), created_at=_now(), **payload.model_dump())
        _sessions[session.id] = session
        return _session_view(session)


@router.get("/sessions", response_model=list[SessionView])
def list_sessions() -> list[SessionView]:
    with _lock:
        return [_session_view(s) for s in _sessions.values()]


@router.get("/sessions/{session_id}", response_model=SessionView)
def get_session(session_id: str) -> SessionView:
    with _lock:
        return _session_view(_get_session(session_id))


@router.patch("/sessions/{session_id}/capacity", response_model=SessionView)
def change_capacity(session_id: str, payload: CapacityChange) -> SessionView:
    with _lock:
        session = _get_session(session_id)
        accommodation = (
            session.accommodation_seats
            if payload.accommodation_seats is None
            else payload.accommodation_seats
        )
        if accommodation > payload.capacity:
            raise HTTPException(
                status_code=422, detail="accommodation_seats cannot exceed capacity"
            )
        booked, held = _seats_in_use(session_id)
        new_cap = {
            SeatType.STANDARD: payload.capacity - accommodation,
            SeatType.ACCOMMODATION: accommodation,
        }
        if any(new_cap[t] < booked[t] + held[t] for t in SeatType):
            raise _conflict("Capacity cannot drop below booked plus held seats")
        session.capacity = payload.capacity
        session.accommodation_seats = accommodation
        _emit(
            "SessionCapacityChanged",
            session_id,
            capacity=payload.capacity,
            accommodation_seats=accommodation,
        )
        offer_policy.on_seat_freed(session_id)
        return _session_view(session)


@router.post(
    "/sessions/{session_id}/bookings",
    response_model=Booking,
    status_code=status.HTTP_201_CREATED,
)
def create_booking(session_id: str, payload: CandidateRequest) -> Booking:
    with _lock:
        session = _get_session(session_id)
        if session.status != SessionStatus.OPEN:
            raise _conflict(f"Session {session_id} is {session.status.value}")
        if _has_active_booking(session_id, payload.candidate_id):
            raise _conflict(f"Candidate {payload.candidate_id} is already booked")
        seat_type = _fitting_seat(payload.accommodation, _free_seats(session))
        if seat_type is None:
            raise _conflict("No seat available for this candidate; join the waitlist")
        booking = Booking(
            id=str(uuid4()),
            session_id=session_id,
            seat_type=seat_type,
            status=BookingStatus.BOOKED,
            created_at=_now(),
            **payload.model_dump(),
        )
        _bookings[booking.id] = booking
        _emit("BookingCreated", session_id, booking_id=booking.id)
        return booking


@router.get("/sessions/{session_id}/bookings", response_model=list[Booking])
def list_session_bookings(session_id: str) -> list[Booking]:
    with _lock:
        _get_session(session_id)
        return [b for b in _bookings.values() if b.session_id == session_id]


@router.post("/bookings/{booking_id}/cancel", response_model=Booking)
def cancel_booking_endpoint(booking_id: str) -> Booking:
    return cancel_booking(booking_id)


@router.post(
    "/sessions/{session_id}/waitlist",
    response_model=WaitlistEntryView,
    status_code=status.HTTP_201_CREATED,
)
def join_waitlist(session_id: str, payload: CandidateRequest) -> WaitlistEntryView:
    with _lock:
        _get_session(session_id)
        if _has_active_booking(session_id, payload.candidate_id):
            raise _conflict(f"Candidate {payload.candidate_id} is already booked")
        if _is_waitlisted(session_id, payload.candidate_id):
            raise _conflict(f"Candidate {payload.candidate_id} is already on the waitlist")
        entry = WaitlistEntry(
            id=str(uuid4()), session_id=session_id, joined_at=_now(), **payload.model_dump()
        )
        _waitlist[entry.id] = entry
        _emit(
            "WaitlistJoined",
            session_id,
            waitlist_entry_id=entry.id,
            candidate_id=entry.candidate_id,
        )
        offer_policy.on_seat_freed(session_id)
        return next(v for v in _waitlist_view(session_id) if v.id == entry.id)


@router.get("/sessions/{session_id}/waitlist", response_model=list[WaitlistEntryView])
def get_waitlist(session_id: str) -> list[WaitlistEntryView]:
    with _lock:
        _get_session(session_id)
        return _waitlist_view(session_id)


@router.get("/candidates/{candidate_id}/bookings", response_model=CandidateBookings)
def my_bookings(candidate_id: str) -> CandidateBookings:
    """Everything the My bookings page shows a candidate, including pending offers."""
    with _lock:
        return CandidateBookings(
            candidate_id=candidate_id,
            bookings=[b for b in _bookings.values() if b.candidate_id == candidate_id],
            offers=[o for o in _offers.values() if o.candidate_id == candidate_id],
            waitlist=[
                v
                for session_id in _sessions
                for v in _waitlist_view(session_id)
                if v.candidate_id == candidate_id
            ],
        )


@router.get("/offers/{offer_id}", response_model=SeatOffer)
def get_offer(offer_id: str) -> SeatOffer:
    with _lock:
        return _get_offer(offer_id)


@router.post("/offers/{offer_id}/accept", response_model=Booking)
@router.post("/bookings/offers/{offer_id}/accept", response_model=Booking)
def accept_offer_endpoint(offer_id: str) -> Booking:
    return accept_offer(offer_id)


@router.post("/offers/{offer_id}/decline", response_model=SeatOffer)
@router.post("/bookings/offers/{offer_id}/decline", response_model=SeatOffer)
def decline_offer_endpoint(offer_id: str) -> SeatOffer:
    return decline_offer(offer_id)


@router.get("/outbox", response_model=list[OutboxEvent])
def list_outbox(pending_only: bool = False) -> list[OutboxEvent]:
    with _lock:
        return [e for e in _outbox if not (pending_only and e.relayed)]


@router.post("/outbox/relay", response_model=RelayResult)
def relay_outbox_endpoint() -> RelayResult:
    return RelayResult(relayed=relay_outbox())


@router.get("/reconciliation", response_model=ReconciliationReport)
def reconciliation() -> ReconciliationReport:
    return reconcile()

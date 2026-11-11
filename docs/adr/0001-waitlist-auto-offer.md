# ADR 0001: Automatically offer freed seats to the waitlist

- Status: Accepted
- Ticket: MBA-3829
- Supersedes: the legacy rule recorded in the scheduling-service ADR 0002 that
  `usp_CancelBooking` never promotes anyone from the waitlist.

## Context

In the legacy system, a cancelled seat goes back into general availability, and center
staff promote waitlisted candidates by hand. Candidates at the top of the waitlist depend
on staff noticing that a seat has freed up.

## Decision

This is a deliberate change from legacy behaviour. When a seat frees up in an OPEN session,
`WaitlistOfferPolicy` (`app/scheduling.py`) offers it automatically. A seat frees up when a
booking is cancelled, when capacity increases, or when an offer is declined or expires.

- The offer goes to the lowest-position waitlist entry whose accommodation needs fit the free
  seat. A candidate who needs an accommodation (for example ET25) can only take an
  accommodation seat. If none is free, that candidate is skipped and keeps their position.
  Other candidates take a standard seat first and an accommodation seat if no standard seat
  is free.
- The seat is held while the offer is PENDING. A held seat is not counted in
  `seats_available` and cannot be booked by anyone else.
- Offers expire after `scheduling.waitlist.offer-ttl`. This is set through the environment
  variable `SCHEDULING_WAITLIST_OFFER_TTL_SECONDS` and defaults to 24h. The
  `waitlist-offer-expiry` job expires overdue offers.
- Accepting an offer books the candidate and removes their waitlist entry. Declining or
  expiry also removes the entry, and the seat is offered to the next eligible candidate. If
  no candidate is left, the seat becomes generally available.
- Every change writes an outbox event (`SeatOffered`, `SeatOfferAccepted`,
  `SeatOfferDeclined`, `SeatOfferExpired`, plus the booking and waitlist events). The
  `scheduling-outbox-relay` job projects these events into the legacy `Booking` /
  `Waitlist` read model. `GET /api/v2/reconciliation` compares the modern and legacy sides.
- All writes happen under one process-wide lock, so two seats freed at the same time
  produce two offers in position order and never two offers for the same entry.

## Consequences

- Staff no longer need to promote candidates by hand. The waitlist drawer shows the state of
  each offer.
- Legacy readers see an accepted offer as a normal BOOKED row after the relay runs. Legacy
  has no concept of an offer, so a held seat appears there only as "not booked".
- The in-memory lock only covers a single process. A deployment with several instances
  would need a database row lock or a unique constraint on pending offers per waitlist entry.

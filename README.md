# Payments Demo API

A small, intentionally readable FastAPI service modelling a payments /
transactions domain. It exists to demonstrate CI/CD, QA automation,
Devin Review and JIRA workflows on a banking-flavoured codebase — not to be a
real payments system.

## Endpoints

| Method | Path                        | Description                    |
| ------ | --------------------------- | ------------------------------ |
| GET    | `/health`                   | Health check + transaction count |
| POST   | `/transactions`             | Create a transaction (201)     |
| GET    | `/transactions`             | List transactions              |
| GET    | `/transactions/{id}`        | Get a transaction by id (404 if unknown) |
| GET    | `/ops/jobs`                 | Jobs registered on the in-app scheduler |
| POST   | `/ops/jobs/{name}/run`      | Run a job (`dry_run=true` by default)  |
| POST   | `/ops/incidents/{scenario}` | Simulate an incident (always 500)      |
| POST   | `/api/v2/sessions`          | Create a test-center session (201)     |
| GET    | `/api/v2/sessions`          | List sessions with seat availability   |
| GET    | `/api/v2/sessions/{id}`     | Session seats: booked, held, available (404 if unknown) |
| PATCH  | `/api/v2/sessions/{id}/capacity` | Change capacity; an increase triggers seat offers (409 below booked + held) |
| POST   | `/api/v2/sessions/{id}/bookings` | Book a seat (201; 409 if no fitting seat) |
| GET    | `/api/v2/sessions/{id}/bookings` | List a session's bookings         |
| POST   | `/api/v2/bookings/{id}/cancel` | Cancel a booking; the freed seat is offered to the waitlist |
| POST   | `/api/v2/sessions/{id}/waitlist` | Join the waitlist (201; 409 if already booked/waitlisted) |
| GET    | `/api/v2/sessions/{id}/waitlist` | Waitlist with positions and pending offers |
| GET    | `/api/v2/candidates/{id}/bookings` | A candidate's bookings, offers and waitlist entries |
| GET    | `/api/v2/offers/{id}`       | Get a seat offer                       |
| POST   | `/api/v2/offers/{id}/accept` | Accept a pending offer and book the seat (also under `/api/v2/bookings/offers/...`; 409 if not pending or expired) |
| POST   | `/api/v2/offers/{id}/decline` | Decline a pending offer; the seat is offered to the next candidate |
| GET    | `/api/v2/outbox`            | Scheduling outbox events               |
| POST   | `/api/v2/outbox/relay`      | Project outbox events into the legacy Booking / Waitlist tables |
| GET    | `/api/v2/reconciliation`    | Compare modern and legacy bookings and waitlist |
| GET    | `/app`                      | Scheduling UI: My bookings (Accept/Decline) and the staff waitlist drawer |

Transactions are stored in an in-memory dict, so state resets on restart and
no database is required.

### Waitlist auto-offer

When a seat frees up in an OPEN session (a cancellation, a capacity increase, or an offer
that is declined or expires), it is offered to the lowest-position waitlist entry whose
accommodation needs fit the seat. The seat is held until that candidate accepts or
declines, or the offer expires. The offer TTL is set with
`SCHEDULING_WAITLIST_OFFER_TTL_SECONDS` and defaults to 24h. The `waitlist-offer-expiry`
and `scheduling-outbox-relay` jobs run on the in-app scheduler. See
`docs/adr/0001-waitlist-auto-offer.md`.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Interactive docs: http://127.0.0.1:8000/docs

Example:

```bash
curl -X POST http://127.0.0.1:8000/transactions \
  -H 'Content-Type: application/json' \
  -d '{"from_account":"ES9121000418450200051332","to_account":"GB29NWBK60161331926819","amount":"125.50","currency":"EUR","reference":"Invoice 42"}'
```

## Quality checks

```bash
ruff check . && ruff format --check .
pytest
```

## CI/CD

`.github/workflows/ci.yml` runs on every push and pull request to `main`:
Python 3.11 setup, dependency install, `ruff` lint/format check and `pytest`.
A stubbed `deploy` job (no real secrets) illustrates a deployment stage that
runs only after tests pass on `main`.

## Repository layout for the Access workshop

- `jobs/` — five legacy cron scripts awaiting migration onto `app/scheduler.py`
  (one unit of work each; excluded from ruff on purpose).
- `app/jobs/` — migrated jobs; `heartbeat.py` is the reference shape.
- `.devin/blueprint.yaml` — git-backed environment (Python 3.11, Azure CLI + DevOps extension).
- `.devin/plugins/payments-workshop/` — the repo's plugin: always-on rules, an ADO rule,
  three skills, ADO MCP.
- `.devin/skills/migrate-jobs/` — dynamic workflow that fans the migration out.
- `demo/` — walkthrough (`WORKSHOP.md`), automation definitions, ADO work items + seed script.

## Demo notes

- `tests/` covers the health check, create and list endpoints.
- `GET /transactions/{id}` deliberately has **no test yet** — a good live
  exercise for adding QA coverage.

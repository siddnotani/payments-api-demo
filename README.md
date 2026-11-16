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
| GET    | `/analytics/summary`        | Per-currency count/total/min/max/avg   |
| GET    | `/analytics/by-account/{account}` | Sent/received counts and totals for an account (404 if none) |

Transactions are stored in an in-memory dict, so state resets on restart and
no database is required.

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

## Analytics

`GET /analytics/summary` returns the overall transaction count plus one breakdown per
currency that has transactions (`count`, `total_amount`, `min_amount`, `max_amount`,
`avg_amount`). Optional filters: `currency` (`EUR`/`GBP`/`USD`) and `since`/`until`
(ISO 8601, inclusive bounds on `created_at`; naive values are treated as UTC). Totals are
exact; averages are rounded half-up to 2 decimal places.

`GET /analytics/by-account/{account}` returns `sent_count`, `received_count` and
`sent_total`/`received_total` keyed by currency, or 404 if the account has no transactions.

```bash
curl http://127.0.0.1:8000/analytics/summary
curl 'http://127.0.0.1:8000/analytics/summary?currency=EUR&since=2026-01-01T00:00:00Z&until=2026-12-31T23:59:59Z'
curl http://127.0.0.1:8000/analytics/by-account/ES9121000418450200051332
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

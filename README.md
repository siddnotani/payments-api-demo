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
| DELETE | `/transactions/{id}`        | Cancel (remove) a transaction (204)      |

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

## Demo notes

- `tests/` covers the health check, create and list endpoints.
- `GET /transactions/{id}` deliberately has **no test yet** — a good live
  exercise for adding QA coverage.

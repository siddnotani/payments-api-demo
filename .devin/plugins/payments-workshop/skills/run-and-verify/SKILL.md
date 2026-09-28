---
name: run-and-verify
description: Boot payments-api-demo locally and prove a change works end-to-end (health, transactions, ops endpoints). Use before opening any PR that touches app/.
---

# Run and verify

1. `pip install -r requirements.txt` (skip if the snapshot already has them).
2. Start the API: `uvicorn app.main:app --port 8000 &` and wait for `GET /health` → 200.
3. Exercise the paths your change touches with `curl`, e.g.
   - `curl -s localhost:8000/health`
   - `curl -s -X POST localhost:8000/transactions -H 'Content-Type: application/json' -d '{"from_account":"A","to_account":"B","amount":"10.00","currency":"EUR"}'`
   - `curl -s localhost:8000/ops/jobs`
4. Run `ruff check . && ruff format --check . && pytest -q`.
5. If the change is user-visible, record a short screen recording of the Swagger UI at
   `/docs` exercising it and attach it to the PR.
6. Kill the server. Report exactly which commands you ran and their output in the PR body.

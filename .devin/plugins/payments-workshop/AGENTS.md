# payments-api-demo — always-on rules

- Python 3.11, FastAPI, in-memory store. No database, no external services in tests.
- Before opening a PR run `ruff check . && ruff format --check . && pytest -q`; all three must pass.
- Never edit `jobs/*.py` in place. Legacy scripts are migrated onto `app.scheduler` (see
  `/payments-workshop:legacy-job-migration`) and then deleted.
- Amounts are `Decimal`, never `float`. Timestamps are timezone-aware UTC.
- Every new endpoint ships with a pytest in `tests/` and a row in the README endpoint table.
- Work items live in Azure DevOps. Reference them as `AB#<id>` in commit messages and PR titles
  so ADO links the PR to the work item.

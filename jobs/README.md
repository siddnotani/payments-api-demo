# Legacy cron jobs

Five standalone scripts, each wired into crontab on the batch host
(see `crontab.txt`). They pre-date the API and share no code with it:
each re-implements config loading, logging and file handling in its own way.

**Migration target:** every script becomes a function registered with
`app.scheduler.job(...)`, is listed by `GET /ops/jobs`, is runnable via
`POST /ops/jobs/{name}/run?dry_run=true`, has a pytest under `tests/jobs/`,
and the script is deleted. `crontab.txt` shrinks by one line per migrated job.

| Script | Schedule | What it does | Known smells |
| --- | --- | --- | --- |
| `reconcile_ledger.py` | `0 2 * * *` | Compares booked vs settled totals per currency | `utcnow()`, `%`-formatting, prints instead of logs, `os.system` |
| `export_settlements.py` | `15 3 * * *` | Writes yesterday's settlement CSV to `/var/exports` | hard-coded paths, manual CSV, bare `except` |
| `notify_overdue.py` | `0 8 * * 1-5` | Emails ops about pending transactions older than 3 days | `smtplib` inline, secrets from `os.environ` w/o validation |
| `refresh_fx_rates.py` | `*/30 * * * *` | Pulls FX rates and caches them to disk | `urllib` without timeout, pickle cache, retry loop w/ `time.sleep` |
| `archive_transactions.py` | `0 4 1 * *` | Moves transactions older than 90 days to an archive JSON | `optparse`, global mutable state, no dry-run |

Each row is one unit of work for the migration workflow
(`.devin/skills/migrate-jobs/workflow.py`) and one ADO work item
(`demo/ado/work-items.json`).

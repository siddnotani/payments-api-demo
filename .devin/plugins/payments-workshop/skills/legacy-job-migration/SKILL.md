---
name: legacy-job-migration
description: Migrate one legacy cron script in jobs/ onto the in-app app.scheduler registry with tests, then delete the script and its crontab line. Use for any task that mentions jobs/, crontab.txt, or "migrate <job>".
---

# Migrate a legacy job

Input: one script name, e.g. `reconcile_ledger`.

1. Read `jobs/<name>.py` and its row in `jobs/README.md` (schedule + known smells).
2. Create `app/jobs/<name>.py`:
   - a function decorated `@job("<name>", schedule="<cron from crontab.txt>", description=...)`
   - signature `(ctx: JobContext) -> JobResult`; honour `ctx.dry_run` (no writes/sends when true)
   - `Decimal` for money, `ctx.now` instead of `utcnow()`, `logging` instead of `print`,
     `pathlib` + configurable paths via a small settings dataclass, no `os.system`, no pickle,
     explicit exceptions, `argparse`-free (the API triggers it).
3. Import the module in `app/jobs/__init__.py` so it registers.
4. Add `tests/jobs/test_<name>.py`: at least one dry-run test with a temp file / fake data,
   one edge case from the "known smells" column.
5. Delete `jobs/<name>.py`, remove its line from `jobs/crontab.txt`, delete its row in
   `jobs/README.md`.
6. Run `/payments-workshop:run-and-verify`; confirm `GET /ops/jobs` lists the job.
7. Keep the change to that one job; other scripts are other people's work.

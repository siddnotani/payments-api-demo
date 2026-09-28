# 3 · Nightly chore (schedule)

**Trigger:** Schedule `0 6 * * 1-5` (weekdays 06:00 Europe/London).

**Action — Start session** (repo `payments-api-demo`, Lite mode):
```
Nightly maintenance for payments-api-demo. Do all three, one PR:
1. Bump any dependency in requirements.txt with a release ≥7 days old that keeps tests green.
2. Regenerate the endpoint table in README.md from app/main.py routes; fix drift.
3. Run `ruff check --select ALL --statistics` and fix the two most common new rule categories
   if the fix is mechanical.
If there is nothing to do, do not open a PR; post "nothing to do" in the automation summary.
```

**Limits:** 1/day · 3 ACUs · no concurrency.

**Demo:** "Run now" on the automation; show it deciding whether there is work.

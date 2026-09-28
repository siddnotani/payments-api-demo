---
name: migrate-jobs
description: Run the dynamic workflow that migrates every legacy script in jobs/ onto app.scheduler — one agent per job, independent verification, one roll-up PR. Use when asked to migrate the legacy jobs, "fan out the jobs migration", or resume a previous migration run.
---

# Migrate legacy jobs (dynamic workflow)

Use the `run_workflow` tool:

- `workflow_name`: `migrate-legacy-jobs`
- `script_path`: the absolute path of `workflow.py` next to this file
- `run_id`: pass the `wfr-...` id of an earlier run to resume it (completed agents replay).

Before running, tell the user: one lite inventory agent, one migrate + one verify agent per
legacy script (5 today), one roll-up agent — about 12 child sessions, each billed as ACUs.

While it runs, follow progress with `get_workflow_output`. If an agent overruns its soft limit,
`message_workflow_agent` it for a status before killing anything.

When it finishes, report the roll-up PR URL and the "needs a human" list verbatim. Offer to
open the failing jobs as ADO work items.

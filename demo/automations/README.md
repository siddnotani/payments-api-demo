# Automations used in the workshop

Each file is the content of one Devin automation (trigger → conditions → action → limits),
written so it can be pasted into the automation editor or applied with the Terraform provider.
Order matches the demo storyline.

| # | File | Trigger | What it shows |
| - | --- | --- | --- |
| 0 | `00-suggest-for-me.md` | — | Devin proposes the automations for this repo ("Suggest for me") |
| 1 | `01-ado-work-item-assigned.md` | Webhook (ADO Service Hook: work item updated) | Ticket assigned → session → PR → board updated, Teams gate |
| 2 | `02-self-healing-ci.md` | GitHub check run failed | CI failure → fix → auto-review → merge-conflict auto-fix, with queueing |
| 3 | `03-nightly-chore.md` | Schedule | Nightly dependency/README/dead-code chore |
| 4 | `04-incident-webhook.md` | Webhook (alert) | The hand-built version of on-call: alert → RCA → fix PR |

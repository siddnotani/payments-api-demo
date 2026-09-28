# Live demo — steps and pre-prep

Repo: the merged `payments-api-demo` (main). Everything below assumes the pre-prep is done the day before.

## Pre-prep (do before the workshop)

1. **Azure DevOps**
   - Create/choose an ADO project; run `demo/ado/seed_work_items.sh` (needs `ADO_ORG_URL`, `ADO_PROJECT`, `az` logged in). Note the IDs of the "Refund endpoint" and "FX provider timeout" items.
   - Add a Service Hook: Work item updated → webhook → the Devin automation URL (created in step 2).
2. **Automations (create now, leave disabled)**
   - `demo/automations/01-ado-work-item-assigned.md` (webhook + conditions + limits). Paste the URL into the ADO service hook.
   - `demo/automations/02-self-healing-ci.md` and `03-nightly-chore.md` (only shown, not run).
3. **Plugin**
   - Install `.devin/plugins/payments-workshop` at org scope in Customize → Plugins. Confirm the auto-migrated `knowledge` plugin shows next to it.
4. **Dynamic workflow (warm run)**
   - Run the `migrate-jobs` workflow once end-to-end on a throwaway branch the day before so you have a finished run to show if the live one is slow. Record the run id.
   - Check Dynamic Workflows are enabled for the org.
5. **Extras**
   - CLI: `devin` CLI logged in on the laptop, repo cloned locally, `devin ssh` working once.
   - Code scan: start a security + dead-code scan on the repo the night before (takes minutes); keep the Findings tab open.
   - On-Call / Migrations: open the beta UIs in tabs; for On-Call have a PagerDuty test service pointed at the automation, or use `POST /ops/incidents/fx_timeout`.
6. **Laptop**
   - Tabs: Devin Automations, ADO board, GitHub PRs, Customize → Plugins, Workflows, Scans, Teams channel.
   - `uvicorn app.main:app --port 8000` running; Swagger at `/docs`.

## Live steps (≈45 min core, ≈15 min extras)

**1. Suggest for me (3 min)**
- Automations → Create → "Suggest for me". Pick "Implement ADO work items assigned to Devin". Show the pre-filled trigger/prompt; point at conditions and limits. Close (the real one is already created).

**2. Automations on ADO (12 min)**
- Enable automation 01. In ADO, assign the "Refund endpoint" work item to Devin, add tag `devin`.
- Show: session starts → work item moves to Active → PR opens titled `AB#<id>: …` → ADO comment + Resolved.
- While it runs: open automation 02/03 to show self-healing CI and the schedule; show the concurrency/queue settings.

**3. Plugins (8 min)**
- Customize → Plugins: `knowledge` (migrated) next to `payments-workshop`. Open rules/skills.
- In a session: "Add a rule to the payments-workshop plugin: never log account numbers." Show the diff + approval.

**4. Dynamic workflows (15 min)**
- New session: "Run the migrate-jobs workflow." Show the fan-out (one agent per job).
- Interrupt one migration agent: "Use JSON, not pickle." Then kill the run and resume by run id (use the pre-warmed run if time is short).
- Show the roll-up PR and `GET /ops/jobs` listing the migrated jobs.

**5. Extras (3–4 min each, in order)**
- CLI ⇄ Cloud: start a ticket locally → `/handoff` → `devin ssh <session>` + `devin forward <session> 8000` → `/pickup`.
- Code scans: open the pre-run scan → read 3 findings → Assign to Devin on one.
- On-Call (beta): fire `POST /ops/incidents/fx_timeout` (or PagerDuty test) → show incident notes appearing → fix PR.
- Migrations (beta): open the beta UI, point at the repo's `jobs/` → show plan → start; contrast with step 4.

## Fallbacks
- Automation slow → show the pre-run session/PR from the rehearsal.
- Workflow slow → switch to the pre-warmed run id.
- ADO hook fails → trigger the automation manually with "Run now".

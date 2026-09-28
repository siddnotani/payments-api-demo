# Access onsite — demo walkthrough

Storyline: **from one task to a system that runs itself.** Everything runs on this repo.
Deck first (≈15 min), then demos in this order. Core blocks are the must-shows; extras are
one slide each in the deck and demoed if time allows.

Timing (80 min): deck 15 · core demos 45 (A 20, B 10, C 15) · extras 15 · Q&A 5.

---

## Seeding (day before)

| Step | Command / action | Verify |
| --- | --- | --- |
| Repo | merge the workshop PR to `main`; repo indexed in the org with a snapshot from `.devin/blueprint.yaml` | new session boots with `az` + deps |
| Plugin | Customize → Plugins → upload `.devin/plugins/payments-workshop` at **org** scope (also works from the CLI: `devin plugins install --local .devin/plugins/payments-workshop`) | `/payments-workshop:` shows 3 skills in the slash menu |
| ADO | `ADO_ORG_URL=… ADO_PROJECT=… demo/ado/seed_work_items.sh` | 7 work items tagged `devin` on the board |
| ADO hook | Service hook *Work item updated* → automation 01 webhook URL + secret | test event shows in the automation's run log |
| Automations | create 01–04 from `demo/automations/*.md` (or Terraform); leave **01 disabled** so "Suggest for me" can propose it live | four automations listed |
| Broken CI branch | `git checkout -b demo/broken-ci main` → edit `tests/test_api.py` so `test_run_unknown_job_is_404` asserts `status_code == 400` → push (no PR yet) | CI will fail on PR open |
| Beta | On-Call responder configured (PagerDuty sandbox service `payments-api`); Migrations beta pointed at this repo's `jobs/` | both open from the sidebar |
| Voice/Teams | Teams channel "Payments Eng" with Devin installed | `@Devin` replies |

---

## 0 · Opener — "Devin suggests the automations" (5 min)

1. Automations → Create automation → **Suggest for me**.
2. Talk while it thinks: "Devin has watched this org's sessions; it knows where the repetition is."
3. Pick the ADO suggestion → opens pre-filled → walk the editor: trigger, **conditions**, prompt,
   **limits** (ACUs, invocations/hour, concurrency group, queueing), network policy, security profile.
4. Save → this becomes automation 01 (or enable the pre-built one if the suggestion is off).

Fallback: **Generate with Devin** with prompt "automate implementing ADO work items assigned to Devin in payments-api-demo".

## A · Automations on ADO (20 min)

**A1 — Work item → PR (live, 10 min)**
- In ADO assign *Refunds: POST /transactions/{id}/refund* to Devin.
- Show the automation **run log**: webhook payload, matched conditions.
- Open the session: it invokes `/payments-workshop:ado-work-item` (plugin skill), reads the item
  via `az boards`, moves it Active. Point at the **rule** kicking in (AB# in title).
- Let it run in the background; come back at the end of A for the PR + Resolved comment.

**A2 — Self-healing CI (live, 7 min)**
- Open a PR from `demo/broken-ci`. CI goes red → automation 02 fires.
- Show the *no-loop* condition (`head_branch !~ ^devin/ci-fix/`) and the concurrency group.
- Fix lands on the same branch → CI green → Devin Review comments automatically → mention the
  automatic merge-conflict fix as the third link in the chain.

**A3 — Scheduled chore (2 min)**: open automation 03, click **Run now**, show it deciding whether
there is work. Mention Terraform provider / Automations API for managing these as code.

**A4 — Return to A1**: PR `AB#…: Refunds…` open, work item Resolved with comment. If the AC were
ambiguous, show the Teams question that gated it.

## B · Plugins (10 min)

1. Customize → Plugins: show `payments-workshop` (org scope) next to the auto-created
   `knowledge` plugin → "your Knowledge notes were migrated into skills; nothing lost".
2. Open the plugin folder in the repo: `AGENTS.md` (always-on), `rules/azure-devops.md`
   (triggered), `skills/*` (slash-invocable), `.mcp.json` (ADO MCP ships with it).
3. Old vs new (one slide): Knowledge = flat notes, Playbooks = one-off prompts, Skills = files in
   repos → **Plugin = versioned bundle of all of it + tools, installed per person/org/enterprise,
   required or available-to-install, managed by Devin itself.**
4. Live: in a session say *"add a rule to the payments-workshop plugin: never log account
   numbers"* → Devin edits the plugin and asks for approval → approve → visible in Customize.
5. CLI tie-in: `devin plugins info payments-workshop` on the laptop — same plugin, local sessions.

## C · Dynamic Workflows (15 min)

1. Show `jobs/README.md`: five legacy cron scripts, one target (`app.scheduler`), one reference
   job already migrated (`app/jobs/heartbeat.py`).
2. Open `.devin/skills/migrate-jobs/workflow.py`: inventory → per-job migrate → verify → roll-up.
   Point at `pipeline` (no barrier), the structured-output schemas, `WorkflowAgentError` handling,
   soft time limits, `mode="lite"` for cheap stages.
3. Start it: session → *"run the migrate-jobs workflow"* (the skill tells Devin how). Cost line:
   ~12 child sessions.
4. Show the workflow panel: phases, x/y, ACUs per agent. Interrupt one migrate agent with
   `message_workflow_agent` ("use JSON not pickle") → it adapts.
5. Kill the run, **resume with the run_id**: completed agents replay instantly. This is the surprise.
6. Roll-up PR appears with a "needs a human" section. Mention: after a workflow works once, it is
   saved as a skill (this is what `.devin/skills/migrate-jobs` is).

## Extras (one slide each; demo if time)

**X1 — CLI ⇄ Cloud (5 min).** On the laptop: `devin` in the repo → start the FX filter ticket
→ `/handoff` → cloud session continues → `devin ssh` into the VM, `curl localhost:8000/ops/jobs`
→ `devin forward 8000` and open Swagger locally → `/pickup` back. Mention SWE-2 selector and
handoff from Claude Code / Cursor.

**X2 — Code Scans (5 min).** Code Scans → new scan on `payments-api-demo` (security + dead code +
test coverage). Findings tab: `jobs/refresh_fx_rates.py` pickle, `os.system` in
`reconcile_ledger.py`, untested `GET /transactions/{id}`. **Assign to Devin** on one → fix PR.
Show *scan new commits* and scheduling. Mention Security Swarm for multi-repo + attack paths.

**X3 — Devin On-Call (Beta, 5 min).** Trigger PagerDuty incident via
`curl -X POST localhost:8000/ops/incidents/fx_timeout` behind the monitor (or the PD test
incident). Responder triages, posts incident notes, opens the fix PR (same bug as the ADO item
*FX provider timeout returns 500*), replies in Teams. Resolve → post-mortem draft.
Contrast with automation 04 (hand-built) — "this is that, productised".

**X4 — Devin Migrations (Beta, 5 min).** Point Migrations at `jobs/` → inventory, plan review,
parallel execution, progress, needs-attention rollup, PRs. Contrast with C: "workflow = you
write the orchestration; Migrations = the orchestration is the product". *(Exact UI flow to be
confirmed against the beta before the day.)*

---

## Prompts cheat-sheet

```
# Opener fallback
Generate with Devin: "Automate implementing Azure DevOps work items that get assigned to Devin in payments-api-demo; use the payments-workshop plugin skills."

# Plugins
"Add a rule to the payments-workshop plugin: never log account numbers; mask all but the last 4 chars."

# Dynamic workflow
"Run the migrate-jobs workflow on this repo."
"Resume workflow run <wfr-…>."

# CLI
devin            # in repo
/handoff
devin ssh <session>
devin forward <session> 8000
/pickup
```

## If something is down

| Broken | Do instead |
| --- | --- |
| ADO service hook not firing | trigger 01 with a curl of a saved payload (`demo/ado/sample-payload.json` — save one from the first real event) |
| Suggest for me returns nothing useful | enable pre-built automation 01 and narrate what it suggested in rehearsal |
| Workflow enterprise toggle off | walk the script + a recorded run's panel |
| Beta features unavailable | slides X3/X4 only |

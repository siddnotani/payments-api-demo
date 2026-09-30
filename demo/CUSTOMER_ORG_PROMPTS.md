# Prompts to run in the customer's Devin org — nothing pushed to their repos

Constraints: their org has the ADO connection and two repos Devin can read; you have **no write access**.
So every artifact lives inside Devin (org plugin, automations, sessions, scans), and demos end with a
**reviewed diff inside the session** rather than an opened PR. ADO comments / state changes go through
Devin's ADO connection. Replace `<REPO>` with one of their two repos and `<ADO_PROJECT>` with the project.

On-Call and Migrations (beta) run in your own org on `payments-api-demo` — see `LIVE_DEMO_STEPS.md`.

---

## 0. Pre-prep (day before)

### 0a. Build the org plugin — one session, ~20 min
```
Create an org-scope plugin called `<REPO>-house-rules` using the plugin management tools (do NOT commit
anything to <REPO>; the plugin lives in Devin). Read <REPO> first so the rules match how it is actually
built and tested. Include:

- AGENTS.md (always-on): run the repo's lint + tests before declaring work done; add a test for every new
  endpoint/function; never push, never open PRs — finish with a summary of the diff and the verification
  output; reference Azure DevOps work items as `AB#<id>`; never close ADO items (Resolved is the ceiling).
- rules/azure-devops.md (triggered when a task mentions an ADO work item or AB#): read the item with the
  ADO connection, move it to Active at start, and when done comment on the item with the diff summary +
  verification output and set it to Resolved.
- skills/ado-work-item/SKILL.md: read item → Active → implement on a local branch → lint + test → summary
  → ADO comment + Resolved.
- skills/run-and-verify/SKILL.md: exact install / start / smoke-test / lint / test commands for <REPO>.
- skills/fanout-<UNIT>/SKILL.md + workflow.py: a dynamic workflow that inventories <UNITS — e.g. "every
  module without tests" / "every deprecated API call"> in <REPO>, runs one agent per unit in parallel,
  verifies each result with a separate agent, and reports a structured roll-up (what passed, what needs
  a human, diff per unit). Resumable by run id. No pushes.
- hooks: a pre-completion hook that runs lint + tests and blocks "done" if they fail.
- MCP: Azure DevOps.

Ask me for approval before saving the plugin.
```
Then: Customize → Plugins → make it **Required** at org scope.

### 0b. Automations (UI, ~10 min, create disabled)
- **ADO work item assigned to Devin** — trigger: ADO work item updated; conditions: assigned to Devin AND tag `devin`; prompt: `/<REPO>-house-rules:ado-work-item AB#{{id}}`; limits: 6 ACUs/run, 10 runs/hour, concurrency group `ado` = 3, queue when full.
- **Failing CI** — trigger: check-run failed on `<REPO>`; condition: branch not starting `devin/`; prompt: diagnose, propose the fix as a diff, comment findings on the linked ADO item.
- **Weekday chore** — schedule `0 6 * * 1-5`; prompt: report outdated deps and lint drift as a summary, no code changes.

### 0c. ADO work items (UI or `az boards`, ~5 min)
Create 4 items in `<ADO_PROJECT>`: two small features, one bug, one tagged for the fan-out. Tag none with `devin` yet.

### 0d. Code scan (~2 min to start)
Scans → New → `<REPO>` → security + dead code + test coverage. Runs read-only; finished by the workshop.

### 0e. Fan-out rehearsal (~15 min, optional but recommended)
```
Run the fanout-<UNIT> workflow from the <REPO>-house-rules plugin on <REPO>. Post the run id when it starts.
```
Note the run id as the fallback for demo 4.

---

## Live demos

### 1. Opener — Devin suggests the automations (no prompt)
Automations → Create → **Suggest for me**. Pick the ADO one; show pre-filled trigger, conditions, limits. Close it (yours already exists).

### 2. Automations on ADO
Enable the ADO automation. In ADO, assign feature item #1 to Devin and add tag `devin`. Narrate: hook → conditions → session → Active → implementation → tests → ADO comment with diff summary → Resolved.

Fallback (new session):
```
/<REPO>-house-rules:ado-work-item AB#<id>
```

### 3. Plugins
Customize → Plugins: the auto-migrated `knowledge` plugin next to `<REPO>-house-rules`. Then:
```
Add a rule to the <REPO>-house-rules plugin: never log or hard-code customer identifiers or secrets;
redact them in examples and tests. Bump the version, show me the diff, ask before saving.
```

### 4. Dynamic workflows
```
Run the fanout-<UNIT> workflow from the <REPO>-house-rules plugin on <REPO>. Post the run id when it starts.
```
Mid-run: `Interrupt the agent on <unit>: <small change of approach>. Leave the others alone.`
Then stop it and: `Resume workflow run <run id>.` Show the structured roll-up. Slow → open the rehearsal run.

### 5. Code scans (extra)
Open the finished scan → Findings. Read three. **Assign to Devin** on one: the session explains and proposes the fix as a diff (no push).

### 6. CLI ⇄ Cloud (extra)
Laptop needs a read-only clone of `<REPO>` (ask them for a zip/clone URL beforehand; if that is not possible, use any public repo — this demo is about the CLI, not the code).
```
devin
> Explain how <feature> works and add a test for it. Don't push.
> /handoff
```
```
devin ssh <session>
devin forward <session> <app port>
```
In the cloud session: `/pickup`.

---

### 7–8. On-Call and Migrations (beta) — your org, payments-api-demo
See `LIVE_DEMO_STEPS.md`, step 5.

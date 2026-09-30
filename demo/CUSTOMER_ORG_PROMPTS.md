# Prompts to run in the customer's Devin org — nothing pushed to their repos

Constraints: their org has the ADO connection and two repos Devin can read; you have **no write access**.
So every artifact lives inside Devin (org plugin, automations, sessions, scans), and demos end with a
**reviewed diff inside the session** rather than an opened PR. ADO comments / state changes go through
Devin's ADO connection. Repo: `Believe - Agentic Engineering Labs` (ADO). Replace `<ADO_PROJECT>` with the project.

On-Call and Migrations (beta) run in your own org on `payments-api-demo` — see `LIVE_DEMO_STEPS.md`.

---

## 0. Pre-prep (day before)

### 0a. Build the org plugin — one session, ~20 min
```
Target repo: "Believe - Agentic Engineering Labs" (Azure DevOps). Create an org-scope plugin called
`believe-house-rules` using the plugin management tools (do NOT commit
anything to that repo; the plugin lives in Devin). Read it first so the rules match how it is actually
built and tested. Include:

- AGENTS.md (always-on): run the repo's lint + tests before declaring work done; add a test for every new
  endpoint/function; never push, never open PRs — finish with a summary of the diff and the verification
  output; reference Azure DevOps work items as `AB#<id>`; never close ADO items (Resolved is the ceiling).
- rules/azure-devops.md (triggered when a task mentions an ADO work item or AB#): read the item with the
  ADO connection, move it to Active at start, and when done comment on the item with the diff summary +
  verification output and set it to Resolved.
- skills/ado-work-item/SKILL.md: read item → Active → implement on a local branch → lint + test → summary
  → ADO comment + Resolved.
- skills/run-and-verify/SKILL.md: exact install / start / smoke-test / lint / test commands for the "Believe - Agentic Engineering Labs" repo.
- skills/fanout-<UNIT>/SKILL.md + workflow.py: a dynamic workflow that inventories <UNITS — e.g. "every
  module without tests" / "every deprecated API call"> in the "Believe - Agentic Engineering Labs" repo, runs one agent per unit in parallel,
  verifies each result with a separate agent, and reports a structured roll-up (what passed, what needs
  a human, diff per unit). Resumable by run id. No pushes.
- hooks: a pre-completion hook that runs lint + tests and blocks "done" if they fail.
- MCP: Azure DevOps.

Ask me for approval before saving the plugin.
```
Then: Customize → Plugins → make it **Required** at org scope.

### 0b. Automations — one session, ~10 min (Devin creates them via the automation tools)
```
Create three Devin automations in this org, all DISABLED for now. Ask me to confirm each before saving.

1. "ADO work item → Devin" — trigger: Azure DevOps work item updated in project <ADO_PROJECT>;
   conditions: assigned to Devin AND tag `devin`; prompt: `/believe-house-rules:ado-work-item AB#{{id}}`;
   limits: 6 ACUs per run, max 10 runs/hour, concurrency group `ado` with max 3 parallel, queue when full.
2. "Failing CI" — trigger: check-run / pipeline failed on the "Believe - Agentic Engineering Labs" repo;
   condition: branch does not start with `devin/`; prompt: diagnose the failure, propose the fix as a diff
   in the session (never push), comment the findings on the linked ADO work item.
3. "Weekday chore" — schedule `0 6 * * 1-5` (Europe/London); prompt: report outdated dependencies and
   lint drift in "Believe - Agentic Engineering Labs" as a summary; no code changes, no pushes.

If a trigger or field isn't available for this org's ADO connection, tell me the closest option instead of guessing.
```

### 0c. ADO work items — same or new session, ~5 min
```
Using the Azure DevOps connection, create 4 work items in project <ADO_PROJECT> for the
"Believe - Agentic Engineering Labs" repo. Read the repo first and pick REAL, small, self-contained tasks:
- 2 × User Story: small features (e.g. a missing input validation or a new field on an existing endpoint),
  each doable with tests in under 20 minutes.
- 1 × Bug: something you can actually find in the code (or a plausible edge case with repro steps).
- 1 × Task tagged `fanout`: "<UNIT> sweep" describing the fan-out job for the dynamic workflow.
Each item: clear title, acceptance criteria, files likely involved. Do NOT assign to Devin and do NOT add
the `devin` tag — I'll do that live. Reply with the item ids and titles.
```

### 0d. Code scan — same session, ~2 min
```
Create a code scan on the "Believe - Agentic Engineering Labs" repo: security + dead code + test coverage
(use the default profile if a combined one isn't available). Read-only, no remediation. Confirm with me
before launching and post the scan link when it starts.
```

### 0e. Fan-out rehearsal — new session, ~15 min (optional but recommended)
```
Run the fanout-<UNIT> workflow from the believe-house-rules plugin on the "Believe - Agentic Engineering Labs"
repo. Post the run id as soon as it starts and the structured roll-up when it finishes. No pushes.
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
/believe-house-rules:ado-work-item AB#<id>
```

### 3. Plugins
Customize → Plugins: the auto-migrated `knowledge` plugin next to `believe-house-rules`. Then:
```
Add a rule to the believe-house-rules plugin: never log or hard-code customer identifiers or secrets;
redact them in examples and tests. Bump the version, show me the diff, ask before saving.
```

### 4. Dynamic workflows
```
Run the fanout-<UNIT> workflow from the believe-house-rules plugin on the "Believe - Agentic Engineering Labs" repo. Post the run id when it starts.
```
Mid-run: `Interrupt the agent on <unit>: <small change of approach>. Leave the others alone.`
Then stop it and: `Resume workflow run <run id>.` Show the structured roll-up. Slow → open the rehearsal run.

### 5. Code scans (extra)
Open the finished scan → Findings. Read three. **Assign to Devin** on one: the session explains and proposes the fix as a diff (no push).

### 6. CLI ⇄ Cloud (extra)
Laptop needs a read-only clone of `Believe - Agentic Engineering Labs` (ask them for a zip/clone URL beforehand; if that is not possible, use any public repo — this demo is about the CLI, not the code).
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

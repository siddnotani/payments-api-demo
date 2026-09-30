# Prompts to run in the customer's Devin org

Their org has the Azure DevOps connection; `payments-api-demo` is not there. Replace `<REPO>` with the
repo you pick in their org (any small service with tests is fine) and `<ADO_PROJECT>` with their ADO
project. Run prompt 0 the day before; prompts 1–6 are the live demos.

On-Call and Migrations (beta) stay in your own org on `payments-api-demo` — see `LIVE_DEMO_STEPS.md`.

---

## 0. Pre-prep (day before) — one session, ~30 min

```
Set up <REPO> as a Devin workshop demo repo. Open ONE PR with everything below; do not merge.

1. Plugin `.devin/plugins/<REPO>-house-rules/` with:
   - `.devin-plugin/plugin.json` (name, version 1.0.0, description).
   - `AGENTS.md`: always-on rules — run the repo's lint + tests before every PR, add a test for every
     new endpoint/function, reference Azure DevOps work items as `AB#<id>` in branch names, commit
     messages and PR titles, never close ADO items (Resolved is the ceiling).
   - `rules/azure-devops.md`: triggered rule (when the task mentions an ADO work item / AB#): read the
     item with `az boards work-item show`, move it to Active at start, comment with the PR link and a
     verification summary, set it to Resolved when the PR is open.
   - `skills/ado-work-item/SKILL.md`: end-to-end skill — read item → Active → branch `devin/ab<id>-<slug>`
     → implement → verify → PR titled `AB#<id>: <title>` → comment + Resolved.
   - `skills/run-and-verify/SKILL.md`: how to install, start, smoke-test, lint and test this repo.
   - `hooks/`: a pre-PR hook that runs lint + tests and blocks the PR if they fail.
   - MCP config for Azure DevOps.
2. `.devin/blueprint.yaml`: install deps, Azure CLI + `azure-devops` extension, lint/test/run knowledge.
3. `.devin/skills/fanout-<UNIT>/workflow.py` + `SKILL.md`: a dynamic workflow that inventories
   <UNITS — e.g. "every module without tests" / "every deprecated API call">, runs one agent per unit
   in parallel, verifies each result with a separate agent, and rolls passing branches into one PR.
   Make it resumable by run id and use structured outputs between steps.
4. `demo/automations/`: markdown definitions (trigger, conditions, prompt, limits) for
   (a) ADO work item assigned to Devin → `/<REPO>-house-rules:ado-work-item`,
   (b) failing CI check-run → fix on the same branch, with a no-loop condition,
   (c) weekday 06:00 schedule → dependency/lint chore, no PR if nothing to do.
5. `demo/ado/work-items.json` + `seed_work_items.sh`: 5 realistic work items for this repo
   (2 small features, 1 bug, 2 units for the fan-out), created with `az boards work-item create`.
6. Seed 4–6 findings a code scan will catch (an unused module, a shell call with user input, a
   hard-coded credential in a test fixture, an untested public function). Keep them obvious and in
   one folder.
7. `demo/WORKSHOP.md`: the demo order with the exact prompts below.
```

Then, manually (10 min):
- Merge the PR. Install the plugin at org scope (Customize → Plugins).
- Run `demo/ado/seed_work_items.sh`. Add an ADO Service Hook (work item updated → webhook) pointing at automation (a) once you create it in step 1 below and leave it disabled.
- Create the three automations from `demo/automations/` (disabled).
- Start a code scan (security + dead code + test coverage) on `<REPO>` so it is finished by the workshop.
- Run the fan-out workflow once on a throwaway branch and note the run id (fallback for demo 4).

---

## 1. Opener — Devin suggests the automations (no prompt)

UI only: Automations → Create → **Suggest for me**. Pick the ADO suggestion, show the pre-filled trigger, conditions, limits. Close it (the real one already exists).

## 2. Automations on ADO

Enable automation (a). In ADO, assign work item **"<feature title>"** to Devin and tag it `devin`. Nothing to type; narrate: hook → conditions → session → Active → PR `AB#<id>` → comment → Resolved.

Fallback prompt (if the hook misfires, in a new session):
```
/<REPO>-house-rules:ado-work-item AB#<id>
```

## 3. Plugins

Customize → Plugins: show the auto-migrated `knowledge` plugin next to `<REPO>-house-rules`. Then in a session:
```
Add a rule to the <REPO>-house-rules plugin: never log or commit customer identifiers or secrets;
redact them in examples and tests. Bump the plugin version, show me the diff and ask before rolling it out.
```

## 4. Dynamic workflows
```
Run the fanout-<UNIT> workflow on <REPO>. Post the run id as soon as it starts.
```
While running, in the workflow's session:
```
Interrupt the agent working on <one unit>: <a small change of approach>. Leave the others alone.
```
Then stop the run and:
```
Resume workflow run <run id>.
```
Show the roll-up PR. If slow, open the pre-warmed run from prep.

## 5. Code scans (extra)

Open the finished scan → Findings. Read three. Click **Assign to Devin** on one; show the fix PR and the finding flipping to resolved. Optional: Schedule → weekly, new commits only.

## 6. CLI ⇄ Cloud (extra)

On your laptop in a clone of `<REPO>`:
```
devin
> Implement AB#<small item id> in this repo.
> /handoff
```
```
devin ssh <session>
devin forward <session> <app port>
```
Back in the cloud session: `/pickup`.

---

## 7–8. On-Call and Migrations (beta) — your org, payments-api-demo

See `LIVE_DEMO_STEPS.md`, step 5.

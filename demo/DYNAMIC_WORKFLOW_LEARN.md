# Dynamic workflows — a learning prompt

## Mental model (30 seconds)
A dynamic workflow is a **Python script Devin writes and runs** that orchestrates child Devin sessions.
Each `agent(prompt, schema)` call spawns one child session and waits for its **structured output** (JSON matching
the schema). The script decides the graph: `pipeline` (per-item stages, no barrier) and `parallel` (barrier).
Every completed agent result is **recorded against a run id**, so if you interrupt or kill the run and resume
it, finished agents replay instantly and only the rest run. The webapp shows a workflow panel with phases,
per-agent rows, session links and ACUs. Each agent costs ACUs — that's the trade-off for parallelism.

Workflows fit when a task splits into ~5+ units that each need judgment (per module / endpoint / ticket),
or when a later stage consumes earlier structured results. Not for 1–3 units or mechanical rewrites.

## Prompt — paste into a new session on a repo you can read
```
I want to learn dynamic workflows by watching one run end to end on <REPO>. Do NOT push or open PRs.

1. First, explain in 5 bullets how run_workflow works: agent() → child session → structured output,
   phases, pipeline vs parallel, run id + resume, ACU cost.

2. Then design a small READ-ONLY workflow and show me the script before running it:
   - Phase "inventory" (1 agent, lite mode): list the 4–6 largest modules/packages in the repo, with the
     path and one line on what each does. Structured output: {"units": [{"path", "purpose"}]}.
   - Phase "analyze" (one agent per unit, in parallel, derived from the inventory output — never
     hand-pasted): for each unit report test coverage gaps, risky patterns and one concrete
     improvement. Structured output: {"path", "gaps": [..], "risks": [..], "suggestion", "confidence"}.
   - Phase "verify" (one agent per unit, chained after its analyze agent via pipeline): check the
     analysis against the code and mark each claim confirmed / rejected.
   - Phase "rollup" (1 agent, barrier on all verified results): a Markdown report grouped by unit,
     listing confirmed findings, rejected ones, and what needs a human.
   Set soft_time_limit_minutes (~10) and handle WorkflowAgentError by skipping the unit and noting it
   in the rollup. Declare phase labels so the panel shows x/y progress.

3. Run it with run_workflow and post the run id immediately. Log at every stage boundary so I can
   follow it in the workflow panel.

4. While it runs, wait for me: I will ask you to interrupt one agent with a change of approach
   (message_workflow_agent), and possibly to kill the run so we can resume it with the same run id.

5. At the end, show the rollup, the ACU summary per phase, and offer to save the script as a
   reusable skill (.devin/skills/<name>/workflow.py + SKILL.md) — but do not commit it anywhere.
```

## What to try while it runs
- `Interrupt the agent analysing <unit>: focus only on error handling, ignore test gaps.`
- `Kill the run.` → `Resume workflow run <run id>.` — watch finished agents replay instantly.
- Open a child session from the panel: it has no idea it's in a workflow; its prompt is all it knows.
- Ask: `Change the inventory prompt to 8 units and resume` — see how downstream agents re-run.

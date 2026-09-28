"""Dynamic workflow: migrate every legacy script in jobs/ onto app.scheduler.

Graph:
    inventory (1 agent, lite)  ->  per job: migrate -> verify  (pipeline, no barrier)
                                                    -> rollup (1 agent, barrier)

Each migrate agent works on its own branch and only touches app/jobs/<name>.py,
tests/jobs/test_<name>.py, jobs/<name>.py, jobs/crontab.txt and jobs/README.md.
The two shared files (crontab.txt, README.md) are line-deletes on distinct lines,
so branches merge cleanly; app/jobs/__init__.py is the one real collision, which
the rollup agent resolves when it stacks the branches.

Run with the `run_workflow` tool:
    workflow_name="migrate-legacy-jobs", script_path=<this file>
Resume a stopped run by passing its run_id.
"""

import asyncio
import json

REPO = "github.com/siddnotani/payments-api-demo"
BASE_BRANCH = "main"

META = {
    "name": "migrate-legacy-jobs",
    "description": "Fan out the jobs/ -> app.scheduler migration, one agent per job, verify each, roll up.",
    "product": "payments-api-demo",
    "soft_time_limit_minutes": 25,
    "phases": [
        {"title": "inventory", "detail": "List the legacy scripts and their schedules", "count": 1},
        {"title": "migrate", "detail": "One agent per job: port, test, delete script, push branch"},
        {
            "title": "verify",
            "detail": "Independent check of each branch against the acceptance criteria",
        },
        {
            "title": "rollup",
            "detail": "Stack the passing branches, resolve __init__.py, open one PR",
            "count": 1,
        },
    ],
}

INVENTORY_SCHEMA = {
    "type": "object",
    "properties": {
        "jobs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "schedule": {"type": "string"},
                    "smells": {"type": "string"},
                },
            },
        }
    },
    "required": ["jobs"],
}

MIGRATE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "branch": {"type": "string"},
        "summary": {"type": "string"},
        "open_questions": {"type": "string"},
    },
    "required": ["name", "branch", "summary"],
}

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "branch": {"type": "string"},
        "passed": {"type": "boolean"},
        "findings": {"type": "string"},
    },
    "required": ["name", "branch", "passed", "findings"],
}

ROLLUP_SCHEMA = {
    "type": "object",
    "properties": {"pr_url": {"type": "string"}, "needs_human": {"type": "string"}},
    "required": ["pr_url", "needs_human"],
}


async def inventory():
    return await agent(  # noqa: F821 - provided by the run_workflow runtime shim
        f"In {REPO} (branch {BASE_BRANCH}) read jobs/README.md and jobs/crontab.txt. "
        "Return every legacy script as a job: name (file stem), its cron schedule, and the "
        "'known smells' text. Do not modify anything.",
        phase="inventory",
        schema=INVENTORY_SCHEMA,
        mode="lite",
        repos=[REPO],
        soft_time_limit_minutes=8,
    )


async def migrate(job):
    name = job["name"]
    return await agent(  # noqa: F821
        f"In {REPO}, branch off {BASE_BRANCH} as devin/migrate-{name}. Migrate the legacy cron "
        f"script jobs/{name}.py onto the in-app scheduler exactly as the repository skill "
        "`/payments-workshop:legacy-job-migration` describes (read .devin/plugins/payments-workshop/"
        "skills/legacy-job-migration/SKILL.md first). Job details: "
        + json.dumps(job, sort_keys=True)
        + "\nOnly touch: app/jobs/"
        + name
        + ".py, tests/jobs/test_"
        + name
        + ".py, jobs/"
        + name
        + ".py (delete), the matching single lines in jobs/crontab.txt and jobs/README.md, and add "
        "one import line to app/jobs/__init__.py. Run ruff and pytest; both must pass. Push the "
        "branch, do NOT open a PR. Report branch name, a two-line summary, and anything you had "
        "to guess about the original behaviour.",
        phase="migrate",
        schema=MIGRATE_SCHEMA,
        label=f"migrate-{name}",
        repos=[REPO],
    )


async def verify(migrated):
    name, branch = migrated["name"], migrated["branch"]
    return await agent(  # noqa: F821
        f"In {REPO}, check out branch {branch}. It claims to migrate the legacy job '{name}' onto "
        "app.scheduler. Verify, without fixing anything: (1) jobs/"
        + name
        + ".py is deleted and its "
        "crontab/README lines are gone; (2) app/jobs/"
        + name
        + ".py registers a job with the original "
        "schedule, uses Decimal for money, ctx.now not utcnow(), logging not print, honours dry_run; "
        "(3) tests/jobs/test_"
        + name
        + ".py exists and `pytest -q tests/jobs` passes; (4) `ruff check .` "
        "passes; (5) start the API and confirm GET /ops/jobs lists '" + name + "'. Report passed "
        "true/false and concise findings. Author's summary: "
        + json.dumps(migrated, sort_keys=True),
        phase="verify",
        schema=VERIFY_SCHEMA,
        label=f"verify-{name}",
        mode="lite",
        repos=[REPO],
        soft_time_limit_minutes=12,
    )


async def migrate_and_verify(job):
    try:
        migrated = await migrate(job)
    except WorkflowAgentError as e:  # noqa: F821
        log(f"migrate {job['name']} failed: {e}")  # noqa: F821
        return {
            "name": job["name"],
            "branch": "",
            "passed": False,
            "findings": f"migrate failed: {e}",
        }
    try:
        return await verify(migrated)
    except WorkflowAgentError as e:  # noqa: F821
        return {
            "name": job["name"],
            "branch": migrated["branch"],
            "passed": False,
            "findings": f"verify agent failed: {e}",
        }


async def rollup(results):
    passing = [r for r in results if r["passed"]]
    failing = [r for r in results if not r["passed"]]
    return await agent(  # noqa: F821
        f"In {REPO}, create branch devin/migrate-legacy-jobs from {BASE_BRANCH} and merge these "
        "verified branches into it in order, resolving the only expected conflict "
        "(import lines in app/jobs/__init__.py — keep all of them, sorted): "
        + json.dumps([r["branch"] for r in passing], sort_keys=True)
        + "\nRun ruff and pytest on the result; both must pass. Open ONE pull request titled "
        "'Migrate legacy cron jobs onto app.scheduler'. In the PR body list each migrated job "
        "with its verifier findings, and a 'Needs a human' section for these: "
        + json.dumps(failing, sort_keys=True)
        + "\nReport the PR URL and the needs-human text.",
        phase="rollup",
        schema=ROLLUP_SCHEMA,
        repos=[REPO],
    )


async def main():
    await register_workflow(META)  # noqa: F821
    inv = await inventory()
    jobs = sorted(inv["jobs"], key=lambda j: j["name"])
    log(f"inventory: {len(jobs)} legacy jobs -> {[j['name'] for j in jobs]}")  # noqa: F821
    results = await pipeline(jobs, migrate_and_verify)  # noqa: F821
    for r in results:
        log(f"{r['name']}: {'PASS' if r['passed'] else 'FAIL'} {r['branch']}")  # noqa: F821
    out = await rollup(results)
    log(f"PR: {out['pr_url']}")  # noqa: F821
    if out["needs_human"].strip():
        log(f"Needs a human: {out['needs_human']}")  # noqa: F821


asyncio.run(main())

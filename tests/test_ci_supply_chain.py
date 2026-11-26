"""Guards the CI workflow against supply-chain regressions.

CI must run with a read-only token, use actions pinned to immutable commit SHAs,
not leave the token in the checkout's git config, and install only hash-pinned
dependencies from the generated lock file.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = ROOT / ".github" / "workflows"
LOCK_FILE = ROOT / "requirements.lock"
FULL_SHA = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
WORKFLOWS = sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml"))


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _steps(workflow: dict):
    for job_name, job in workflow["jobs"].items():
        for step in job.get("steps", []):
            yield job_name, step


def test_workflows_exist():
    assert WORKFLOWS


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_token_is_read_only(path):
    workflow = _load(path)
    assert workflow.get("permissions") == {"contents": "read"}
    for job_name, job in workflow["jobs"].items():
        perms = job.get("permissions", workflow["permissions"])
        assert isinstance(perms, dict), f"{job_name}: permissions must be explicit"
        assert all(v in ("read", "none") for v in perms.values()), f"{job_name}: {perms}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_actions_are_pinned_to_commit_sha(path):
    for job_name, step in _steps(_load(path)):
        uses = step.get("uses")
        if uses is None or uses.startswith("./"):
            continue
        assert FULL_SHA.match(uses), f"{job_name}: {uses} is not pinned to a full commit SHA"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_checkout_does_not_persist_credentials(path):
    for job_name, step in _steps(_load(path)):
        if step.get("uses", "").startswith("actions/checkout@"):
            assert step.get("with", {}).get("persist-credentials") is False, job_name


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_pip_installs_require_hashes(path):
    for job_name, step in _steps(_load(path)):
        run = step.get("run", "")
        for line in run.splitlines():
            if re.search(r"\bpip install\b", line):
                assert "--require-hashes" in line, f"{job_name}: {line.strip()}"
                assert "-r requirements.lock" in line, f"{job_name}: {line.strip()}"


def _lock_entries() -> list[str]:
    text = LOCK_FILE.read_text().replace("\\\n", " ")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_lock_file_pins_every_package_with_hashes():
    entries = _lock_entries()
    assert entries
    for entry in entries:
        requirement = entry.split()[0]
        assert re.match(r"^[A-Za-z0-9._-]+==[^\s=]+$", requirement), entry
        assert re.search(r"--hash=sha256:[0-9a-f]{64}", entry), entry


def test_lock_file_covers_direct_requirements():
    locked = {e.split("==")[0].lower() for e in _lock_entries()}
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        name = re.split(r"[\[<>=!~; ]", line, maxsplit=1)[0].lower()
        assert name in locked, f"{name} missing from requirements.lock"

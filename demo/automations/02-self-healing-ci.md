# 2 · Self-healing CI

**Trigger:** GitHub → *Check run* → conclusion `failure`, repo `payments-api-demo`.

**Conditions:**
- `check_run.name` matches `Lint & Test`
- `check_run.check_suite.head_branch` does NOT match `^devin/ci-fix/` (no loops)
- `check_run.check_suite.pull_requests[0].user.login` NOT `dependabot`

**Action — Start session:**
```
CI failed on payments-api-demo (payload below). Pull the failing job log, reproduce locally,
fix the root cause — never skip or delete a test — and push the fix to the SAME PR branch
if the PR was opened by Devin, otherwise open a new PR from devin/ci-fix/<short> against the
PR branch and request review from the PR author. Summarise cause + fix in one comment on the PR.
```

**Limits:** 20/hour · 4 ACUs · concurrency group `ci-fix` = 2, queue.

**Chained behaviour to point out (no extra config):**
- Devin Review auto-reviews the fix PR (rule-based autoreview enabled on the repo).
- If `main` moves and the PR conflicts, Devin's automatic merge-conflict fix runs on its own PR.

**Demo:** push branch `demo/broken-ci` (a test asserting the wrong 404 detail message) → open PR
→ CI red → automation → fix commit → CI green → Review comment. Prepared with
`git checkout demo/broken-ci` (see WORKSHOP.md, "Seeding").

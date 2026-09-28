# 1 · ADO work item assigned to Devin → PR

**Trigger:** Webhook. In Azure DevOps: Project settings → Service hooks → **Web Hooks** →
event *Work item updated*, filter *Assigned To changed* → URL = the automation's webhook URL,
HTTP header `X-Webhook-Secret: <secret>`.

**Conditions (regex on payload):**
- `resource.fields."System.AssignedTo".newValue` matches `Devin`
- `resource.revision.fields."System.Tags"` matches `devin`
- `resource.revision.fields."System.WorkItemType"` matches `User Story|Task|Bug`

**Action — Start session** (repo: `payments-api-demo`, agent mode, Security profile: `workshop`):
```
An Azure DevOps work item was just assigned to you. The webhook payload is below.
Use /payments-workshop:ado-work-item to implement it end to end: read AB#{{resource.workItemId}}
with `az boards work-item show`, move it to Active, implement on branch devin/ab<id>-<slug>,
run /payments-workshop:run-and-verify, open a PR titled "AB#<id>: <title>", comment the PR link
on the work item and set it to Resolved.
If the acceptance criteria are ambiguous, post the question to the Teams channel "Payments Eng"
and wait for an answer before writing code.
```

**Limits:** max 10 invocations/hour · 6 ACUs per session · concurrency group `ado-tickets` = 3 ·
queue when full · network policy on (allowlist `dev.azure.com`).

**Demo:** assign work item "Refunds: POST /transactions/{id}/refund" to Devin in ADO →
automation run appears → session → PR `AB#<id>: Refunds…` → work item Resolved with comment.
Show the run log (matched conditions, payload) and the Teams question if the AC were ambiguous.

---
name: ado-work-item
description: Implement an Azure DevOps work item (AB#<id>) for payments-api-demo from spec to PR, keeping the board in sync. Use when assigned a work item or when an automation passes one in.
---

# Implement an ADO work item

1. `az boards work-item show --id <id> --output json` → read Title, Description, Acceptance Criteria.
2. Move it to Active: `az boards work-item update --id <id> --state Active`.
3. Branch: `git checkout -b devin/ab<id>-<slug>`.
4. Implement. Follow AGENTS.md (Decimal, UTC, tests for every endpoint, README table row).
5. Run `/payments-workshop:run-and-verify`.
6. Open the PR with title `AB#<id>: <title>`; body = what changed, how it was verified,
   anything the acceptance criteria left open.
7. Comment on the work item with the PR link and set state Resolved.
8. Do not close the work item.

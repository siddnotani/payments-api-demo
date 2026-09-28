---
trigger: model_decision
description: Apply when a task mentions an Azure DevOps work item, AB#<id>, a board, a sprint, or asks to update / comment on / close a work item.
---

# Azure DevOps conventions

- Read work items with `az boards work-item show --id <id> --output json` (the `az` CLI is
  installed and logged in via the blueprint). Use the `Description` and
  `Microsoft.VSTS.Common.AcceptanceCriteria` fields as the spec.
- When you start, move the item to **Active**; when the PR is open, move it to **Resolved**
  and add a comment with the PR link and a two-line summary of what you verified:
  `az boards work-item update --id <id> --state Resolved --discussion "<text>"`.
- Never close an item yourself; a human closes after review.
- If acceptance criteria are ambiguous, ask in the PR description rather than guessing, and
  tag the item's `Assigned To` in the comment.

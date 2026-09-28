#!/usr/bin/env bash
# Seed the workshop work items into an Azure DevOps project.
#   ADO_ORG_URL=https://dev.azure.com/<org> ADO_PROJECT=<project> ./demo/ado/seed_work_items.sh
# Requires: az CLI logged in, `az extension add --name azure-devops`, jq.
set -euo pipefail
: "${ADO_ORG_URL:?set ADO_ORG_URL}"; : "${ADO_PROJECT:?set ADO_PROJECT}"
az devops configure --defaults organization="$ADO_ORG_URL" project="$ADO_PROJECT"
here="$(cd "$(dirname "$0")" && pwd)"
jq -c '.[]' "$here/work-items.json" | while read -r item; do
  type=$(jq -r .type <<<"$item"); title=$(jq -r .title <<<"$item")
  desc=$(jq -r .description <<<"$item"); ac=$(jq -r .acceptance <<<"$item"); tags=$(jq -r .tags <<<"$item")
  id=$(az boards work-item create --type "$type" --title "$title" --description "$desc" \
        --fields "Microsoft.VSTS.Common.AcceptanceCriteria=$ac" "System.Tags=$tags" \
        --query id -o tsv)
  echo "AB#$id  $type  $title"
done

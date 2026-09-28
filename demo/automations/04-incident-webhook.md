# 4 · Incident webhook (the hand-built version of On-Call)

**Trigger:** Webhook, called by the alerting tool (Azure Monitor action group / Datadog / a curl).

**Conditions:** `severity` matches `sev1|sev2`; `service` matches `payments-api`.

**Action — Start session:**
```
A production alert fired (payload below). You are first responder for payments-api-demo.
1. Reproduce with `POST /ops/incidents/<scenario>` against a local server.
2. Root-cause it in app/ and post a 5-line RCA to Teams channel "Payments Eng".
3. Open a fix PR (do not merge). Link the ADO bug if one matches the scenario, else create one
   with `az boards work-item create --type Bug`.
```

**Limits:** 5/hour · 6 ACUs · concurrency group `incidents` = 1 (serialise), queue.

**Demo:**
```bash
curl -X POST "$WEBHOOK_URL" -H "X-Webhook-Secret: $SECRET" -H 'Content-Type: application/json' \
  -d '{"severity":"sev2","service":"payments-api","scenario":"fx_timeout","message":"FX rate provider timed out after 5000ms"}'
```
Then contrast with the Beta **Devin On-Call** responder (PagerDuty-native, incident notes,
post-mortem on resolve) — same outcome, zero prompt engineering.

#!/usr/bin/env python
# reconcile_ledger.py - nightly ledger reconciliation (legacy, do not import)
import os
import sys
import json
import datetime

LEDGER = os.environ.get("LEDGER_FILE", "/var/lib/payments/ledger.json")
TOLERANCE = 0.05


def load():
    f = open(LEDGER)
    data = json.load(f)
    f.close()
    return data


def main():
    now = datetime.datetime.utcnow()
    print("[%s] reconcile start" % now.strftime("%Y-%m-%d %H:%M:%S"))
    data = load()
    drift = {}
    for ccy in ("EUR", "GBP", "USD"):
        booked = sum([float(t["amount"]) for t in data if t["currency"] == ccy and t["status"] == "COMPLETED"])
        settled = sum([float(t.get("settled_amount", t["amount"])) for t in data if t["currency"] == ccy and t["status"] == "COMPLETED"])
        if abs(booked - settled) > TOLERANCE:
            drift[ccy] = booked - settled
            print("DRIFT %s booked=%.2f settled=%.2f" % (ccy, booked, settled))
    if drift:
        os.system("echo 'ledger drift detected' | mail -s 'Ledger drift' ops@example.com")
        sys.exit(2)
    print("reconcile ok")


if __name__ == "__main__":
    main()

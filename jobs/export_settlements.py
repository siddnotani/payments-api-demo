#!/usr/bin/env python
# export_settlements.py - dumps yesterday's settled transactions to CSV for the bank upload
import os
import json
import datetime

SRC = "/var/lib/payments/ledger.json"
DST_DIR = "/var/exports"


def main():
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    out = DST_DIR + "/settlements-" + yesterday.strftime("%Y%m%d") + ".csv"
    if os.path.exists(out):
        print("already exported " + out)
        return
    try:
        rows = json.load(open(SRC))
    except:
        print("could not read ledger")
        return
    f = open(out, "w")
    f.write("id,from_account,to_account,amount,currency\n")
    n = 0
    for r in rows:
        if r["status"] != "COMPLETED":
            continue
        if r["created_at"][:10] != str(yesterday):
            continue
        f.write("%s,%s,%s,%s,%s\n" % (r["id"], r["from_account"], r["to_account"], r["amount"], r["currency"]))
        n = n + 1
    f.close()
    print("exported %d rows to %s" % (n, out))


if __name__ == "__main__":
    main()

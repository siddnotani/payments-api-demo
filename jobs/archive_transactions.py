#!/usr/bin/env python
# archive_transactions.py - monthly: move transactions older than 90 days out of the live ledger
import json
import datetime
from optparse import OptionParser

SRC = "/var/lib/payments/ledger.json"
ARCHIVE = "/var/lib/payments/archive-%s.json"

kept = []
archived = []


def split(rows, days):
    global kept, archived
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    for r in rows:
        created = datetime.datetime.strptime(r["created_at"][:19], "%Y-%m-%dT%H:%M:%S")
        if created < cutoff:
            archived.append(r)
        else:
            kept.append(r)


def main():
    parser = OptionParser()
    parser.add_option("-d", "--days", dest="days", type="int", default=90)
    (opts, args) = parser.parse_args()
    rows = json.load(open(SRC))
    split(rows, opts.days)
    stamp = datetime.date.today().strftime("%Y%m")
    json.dump(archived, open(ARCHIVE % stamp, "w"))
    json.dump(kept, open(SRC, "w"))
    print("archived %d, kept %d" % (len(archived), len(kept)))


if __name__ == "__main__":
    main()

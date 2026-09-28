#!/usr/bin/env python
# notify_overdue.py - mails ops about PENDING transactions older than 3 days
import os
import json
import smtplib
import datetime

SRC = "/var/lib/payments/ledger.json"
SMTP_HOST = os.environ["SMTP_HOST"]
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]
TO = "ops@example.com"


def overdue(rows):
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=3)
    result = []
    for r in rows:
        created = datetime.datetime.strptime(r["created_at"][:19], "%Y-%m-%dT%H:%M:%S")
        if r["status"] == "PENDING" and created < cutoff:
            result.append(r)
    return result


def main():
    rows = json.load(open(SRC))
    items = overdue(rows)
    if len(items) == 0:
        print("nothing overdue")
        return
    body = "Overdue pending transactions:\n\n"
    for r in items:
        body = body + "%s %s %s %s\n" % (r["id"], r["amount"], r["currency"], r["created_at"])
    msg = "From: payments@example.com\r\nTo: %s\r\nSubject: %d overdue transactions\r\n\r\n%s" % (TO, len(items), body)
    s = smtplib.SMTP(SMTP_HOST)
    s.login(SMTP_USER, SMTP_PASS)
    s.sendmail("payments@example.com", [TO], msg)
    s.quit()
    print("sent %d" % len(items))


if __name__ == "__main__":
    main()

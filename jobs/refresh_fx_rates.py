#!/usr/bin/env python
# refresh_fx_rates.py - fetches FX rates every 30 min and caches them for the API host
import json
import time
import pickle
import urllib.request

URL = "https://api.exchangerate.host/latest?base=EUR&symbols=GBP,USD"
CACHE = "/var/cache/payments/fx.pkl"
RETRIES = 3


def fetch():
    for i in range(RETRIES):
        try:
            resp = urllib.request.urlopen(URL)
            return json.loads(resp.read())
        except Exception as e:
            print("attempt %d failed: %s" % (i + 1, e))
            time.sleep(5 * (i + 1))
    raise RuntimeError("fx provider unavailable")


def main():
    data = fetch()
    rates = data["rates"]
    rates["EUR"] = 1.0
    with open(CACHE, "wb") as f:
        pickle.dump({"fetched_at": time.time(), "rates": rates}, f)
    print("cached rates: %s" % rates)


if __name__ == "__main__":
    main()

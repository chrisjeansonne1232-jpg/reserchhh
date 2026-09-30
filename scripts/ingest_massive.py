"""Paced, resumable bulk ingestion from the Massive REST API (authenticated with MASSIVE_API_KEY).

Nothing is filled, dropped or transformed: raw JSON pages are cached under data/raw/ (gitignored) and every request outcome
(status, NOT_ENTITLED, exhausted retries) is appended to data/raw/_ingest_log.jsonl so gaps are recorded rather than assumed.
The API key is read from the environment and is never printed or written.

    python scripts/ingest_massive.py daily      # grouped daily bars (adjusted=false), one request per XNYS session
    python scripts/ingest_massive.py splits     # /stocks/v1/splits (all pages)
    python scripts/ingest_massive.py tickers    # reference tickers, active and delisted (all pages)
"""
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import exchange_calendars as xcals
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
BASE = "https://api.massive.com"
MIN_INTERVAL = float(os.environ.get("INGEST_MIN_INTERVAL", "13"))   # measured limit is ~5 requests/min on this plan
START, END = "2024-10-01", "2026-09-29"                              # earliest entitled session verified 2024-10-01 (2024-09-30 -> 429, 2024-09-03 -> 403)

_last = [0.0]
S = requests.Session()


def log(rec):
    RAW.mkdir(parents=True, exist_ok=True)
    with open(RAW / "_ingest_log.jsonl", "a") as f:
        f.write(json.dumps({"t": dt.datetime.now(dt.timezone.utc).isoformat(), **rec}) + "\n")


def get(path, params=None, tries=8):
    key = os.environ["MASSIVE_API_KEY"]
    for k in range(tries):
        wait = MIN_INTERVAL - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            r = S.get(BASE + path if path.startswith("/") else path, params=params, headers={"Authorization": f"Bearer {key}"}, timeout=60)
        except requests.RequestException as e:
            log({"path": path, "params": params, "error": type(e).__name__})
            time.sleep(5 * (k + 1))
            continue
        if r.status_code == 200:
            return r.json()
        log({"path": path, "params": params, "status": r.status_code, "body": r.text[:200]})
        if r.status_code in (403, 404, 410):
            return {"_http": r.status_code, "_body": r.text[:200]}
        time.sleep(15 * (k + 1))   # 429 / 5xx: back off
    return {"_http": "RETRIES_EXHAUSTED"}


def sessions():
    cal = xcals.get_calendar("XNYS")
    return [d.strftime("%Y-%m-%d") for d in cal.sessions_in_range(START, END)]


def ingest_daily():
    out = RAW / "daily"
    out.mkdir(parents=True, exist_ok=True)
    todo = [d for d in sessions() if not (out / f"{d}.json").exists()]
    print(f"daily: {len(todo)} sessions to fetch", flush=True)
    for i, d in enumerate(todo):
        j = get(f"/v2/aggs/grouped/locale/us/market/stocks/{d}", {"adjusted": "false", "include_otc": "false"})
        if "_http" in j:
            print("FAILED", d, j, flush=True)
            continue
        (out / f"{d}.json").write_text(json.dumps(j))
        if i % 20 == 0:
            print(f"  {i}/{len(todo)} {d} n={j.get('resultsCount')}", flush=True)


def paged(path, params, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    pages, url, p = [], path, dict(params)
    while url:
        j = get(url, p)
        if "_http" in j:
            raise RuntimeError(f"{path}: {j}")
        pages.append(j)
        url, p = j.get("next_url"), None
        print(f"  {dest.name}: page {len(pages)}", flush=True)
    dest.write_text(json.dumps(pages))


def ingest_splits():
    paged("/stocks/v1/splits", {"limit": 1000}, RAW / "splits.json")


def ingest_tickers():
    for act in ("true", "false"):
        paged("/v3/reference/tickers", {"market": "stocks", "active": act, "limit": 1000, "type": "CS"}, RAW / f"tickers_active_{act}.json")


if __name__ == "__main__":
    {"daily": ingest_daily, "splits": ingest_splits, "tickers": ingest_tickers}[sys.argv[1]]()

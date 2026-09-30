"""Point-in-time security-master snapshots from Massive (free tier): active common stocks AS OF the first XNYS session of each quarter, 2019-Q1..now.
Unlike the current master (one row per ticker, current issuer only) this lists issuers that were listed on the date -- including names since delisted and
old issuers of re-used tickers. Used ONLY to quantify residual survivorship bias for DAILY_SWING_V1 (which listed names have no bars). Resumable; raw -> data/raw/."""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edgelab.integrity import MarketCalendar
from edgelab.massive import MassiveRest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "massive_pit_master"
OUT.mkdir(parents=True, exist_ok=True)
cal = MarketCalendar("US_EQUITY")
now = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
sess = cal.sessions("2019-01-01", now)
dates = [sess[sess >= q][0] for q in pd.date_range("2019-01-01", now, freq="QS") if (sess >= q).any()]
m = MassiveRest()
for d in dates:
    f = OUT / f"snapshot_{d.date()}.parquet"
    if f.exists():
        continue
    rows, url, p = [], "/v3/reference/tickers", {"market": "stocks", "type": "CS", "date": str(d.date()), "limit": 1000, "sort": "ticker"}
    while url:
        r = m.http.get_json(url, p)
        rows += r.get("results") or []
        url, p = r.get("next_url"), None
    df = pd.DataFrame(rows)
    df["snapshot_date"] = d
    df.to_parquet(f)
    print(d.date(), len(df), f"calls={m.http.n_calls}", flush=True)
(ROOT / "data" / "samples" / "massive_pit_master.provenance.json").write_text(json.dumps(
    {"provider": "Massive REST (free)", "endpoint": "/v3/reference/tickers?market=stocks&type=CS&date=<first session of quarter>", "dates": [str(d.date()) for d in dates],
     "retrieved_at_utc": pd.Timestamp.now(tz="UTC").isoformat(), "transformations": "none"}, indent=1))
print("done")

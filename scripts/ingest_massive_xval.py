"""Massive daily bars for a deterministic stratified sample of tickers -> data/raw/massive_xval_daily.parquet (git-ignored), used ONLY to
cross-validate Alpaca daily bars. Free tier: ~5 req/min and ~2y of aggregates, so this is a sample by construction.
Strata: 10 most liquid, 10 random others (seed 0), 5 with a split inside the window."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edgelab.massive import MassiveRest
from edgelab.providers import ProviderError

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
cols = ["symbol", "session", "close", "volume"]
d = pd.concat([pd.read_parquet(p, columns=cols) for p in sorted((RAW / "alpaca_daily").glob("part-*.parquet"))])
END = d["session"].max()
m = MassiveRest()
start = None
for cand in ("2024-10-01", "2024-11-01", "2024-12-01"):                       # earliest date the free plan serves (measured, not assumed)
    try:
        m.daily("AAPL", cand, cand[:8] + "28")
        start = cand
        break
    except ProviderError as e:
        print("start", cand, "->", str(e)[:120], flush=True)
assert start, "no entitled start date found"
w = d[d["session"] >= start].copy()
w["dv"] = w["close"] * w["volume"]
agg = w.groupby("symbol").agg(dv=("dv", "median"), n=("close", "size"))
agg = agg[agg["n"] >= 200]
liquid = list(agg.sort_values("dv", ascending=False).head(10).index)
rng = np.random.default_rng(0)
others = list(rng.choice(sorted(set(agg.index) - set(liquid)), 10, replace=False))
sp = pd.read_parquet(RAW / "massive_splits_since_2016.parquet")
sp = sp[(pd.to_datetime(sp["execution_date"]) >= start) & (pd.to_datetime(sp["execution_date"]) <= END) & sp["ticker"].isin(d["symbol"].unique())]
splitters = [t for t in sp["ticker"].drop_duplicates() if t not in liquid + others][:5]
sample = liquid + others + splitters
frames = []
for t in sample:
    try:
        f = m.daily(t, start, END.strftime("%Y-%m-%d"))
        f["ticker"] = t
        frames.append(f)
    except ProviderError as e:
        print("skip", t, str(e)[:100], flush=True)
    print(t, len(frames[-1]) if frames else 0, flush=True)
x = pd.concat(frames)
x.to_parquet(RAW / "massive_xval_daily.parquet")
(ROOT / "data" / "samples" / "massive_xval_daily.provenance.json").write_text(json.dumps(
    {"provider": "Massive REST (free)", "start": start, "end": END.strftime("%Y-%m-%d"), "sample": {"liquid": liquid, "random": others, "with_split": splitters},
     "n_bars": int(len(x)), "retrieved_at_utc": pd.Timestamp.now(tz="UTC").isoformat(), "adjusted": False}, indent=1))
print("done", len(x))

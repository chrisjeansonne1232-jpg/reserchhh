"""Massive daily bars for a stratified sample of DAILY_SWING_V1 universe MEMBERS (as of 2025-06-02), for cross-provider requirement R7.
40 names: 14 from the top third of trailing dollar volume, 13 middle, 13 bottom (seed 0). Free tier: 5 req/min, ~2y of aggregates."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edgelab.daily_swing import build_cube, pit_membership
from edgelab.integrity import MarketCalendar
from edgelab.massive import MassiveRest

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
d = pd.read_parquet(RAW / "alpaca_daily_all.parquet")
sess = MarketCalendar("US_EQUITY").sessions("2016-01-04", str(d["date"].max().date()))
cube, _ = build_cube(d, sess)
t = int(sess.searchsorted(pd.Timestamp("2025-06-02")))
member = pit_membership(cube.close, cube.volume, start=t)[t]
cols = np.flatnonzero(member)
dv = pd.DataFrame(cube.close * cube.volume).rolling(60, min_periods=50).median().shift(1).to_numpy()[t, cols]
order = cols[np.argsort(-dv)]
rng = np.random.default_rng(0)
third = len(order) // 3
pick = [c for part, n in ((order[:third], 14), (order[third:2 * third], 13), (order[2 * third:], 13)) for c in rng.choice(part, n, replace=False)]
tickers = sorted({str(cube.spell_ticker[c]) for c in pick})
start = json.loads((ROOT / "data/samples/massive_xval_daily.provenance.json").read_text())["start"]
end = str(d["date"].max().date())
m = MassiveRest()
frames = []
for tk in tickers:
    f = m.daily(tk, start, end)
    f["ticker"] = tk
    frames.append(f)
    print(tk, len(f), flush=True)
x = pd.concat(frames)
x.to_parquet(RAW / "massive_xval_universe_daily.parquet")
(ROOT / "data/samples/massive_xval_universe_daily.provenance.json").write_text(json.dumps(
    {"provider": "Massive REST (free)", "start": start, "end": end, "members_as_of": "2025-06-02", "tickers": tickers, "n_bars": int(len(x)),
     "strata": "top/middle/bottom third of PIT top-1000 by trailing 60-session median dollar volume, 14/13/13, seed 0", "adjusted": False,
     "retrieved_at_utc": pd.Timestamp.now(tz="UTC").isoformat()}, indent=1))
print("done", len(x))

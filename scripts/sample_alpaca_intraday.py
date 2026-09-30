"""Stratified INTRADAY sample from Alpaca SIP: minute bars (04:00-20:00 ET), trades and quotes around the open, for a spread of years,
regimes and security types. Full-universe minute/tick history is infeasible on the free tier (see the coverage note in the report), so this
is explicitly a SAMPLE: it measures data quality and calls the same integrity checks; it is not the research dataset.
Raw pulls -> data/raw/alpaca_intraday/ (git-ignored); summary -> data/samples/alpaca_intraday_sample.summary.json (committed)."""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edgelab.alpaca import AlpacaData
from edgelab.integrity import MarketCalendar, check_cross_provider_daily, check_minute_bars, check_ticks
from edgelab.massive import MassiveRest

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "alpaca_intraday"
RAW.mkdir(parents=True, exist_ok=True)
a, cal = AlpacaData(), MarketCalendar("US_EQUITY")
# (session, why)  -- normal days, early closes, DST edges, a crash, a rename day, the most recent completed session
SESSIONS = [("2016-11-25", "early close (day after Thanksgiving)"), ("2017-03-13", "first Monday after DST start"), ("2018-07-03", "early close"),
            ("2019-06-12", "normal"), ("2020-03-16", "COVID crash, circuit breakers"), ("2021-11-26", "early close"), ("2022-06-09", "FB->META rename day"),
            ("2023-11-06", "first Monday after DST end"), ("2024-07-03", "early close"), ("2025-07-03", "early close (Massive cross-check day)"), ("2026-09-29", "latest completed session")]
TICKERS = {"AAPL": "liquid mega-cap", "ORLY": "liquid mid-cap, 15:1 split 2025-06", "AMS": "illiquid micro-cap", "META": "renamed 2022 (history keyed by current symbol)"}
allgaps, summary = [], {"sessions": [], "notes": "SAMPLE ONLY"}
for sess, why in SESSIONS:
    s = pd.Timestamp(sess)
    o, c = cal.window_utc(s)
    day0 = pd.Timestamp(f"{sess} 04:00", tz="America/New_York").tz_convert("UTC")
    day1 = pd.Timestamp(f"{sess} 20:00", tz="America/New_York").tz_convert("UTC")
    ds = f"alpaca_intraday_{sess}"
    bars = a.bars(list(TICKERS), "1Min", day0, day1)
    bars.to_parquet(RAW / f"minute_{sess}.parquet")
    mb = bars.rename(columns={"symbol": "ticker", "t": "ts"})
    gaps, st = check_minute_bars(mb, cal, ds) if len(mb) else ([], {})
    allgaps += gaps
    row = {"session": sess, "why": why, "minute_bars": int(len(bars)), "per_ticker_bars": bars.groupby("symbol").size().to_dict() if len(bars) else {}, "minute_check": st,
           "gap_kinds": sorted({g.kind for g in gaps})}
    # trades + quotes for two minutes at the regular open, AAPL and ORLY only (bounded rows)
    t_o, t_c = o, o + pd.Timedelta(minutes=2)
    ticks = {}
    for tk in ("AAPL", "ORLY"):
        tr = a.trades(tk, t_o, t_c, max_rows=200_000)
        qu = a.quotes(tk, t_o, t_c, max_rows=200_000)
        tr.to_parquet(RAW / f"trades_{tk}_{sess}.parquet"); qu.to_parquet(RAW / f"quotes_{tk}_{sess}.parquet")
        g, tst = check_ticks(tr, qu, ds, tk, sess)
        allgaps += g
        ticks[tk] = tst
    row["ticks_first_2min_of_open"] = ticks
    summary["sessions"].append(row)
    print(sess, row["minute_bars"], {k: v.get("n_quotes") for k, v in ticks.items()}, flush=True)

# cross-provider minute check on the one day where Massive minute aggregates are entitled and we hold a comparison (AAPL 2025-07-03)
m = MassiveRest()
ref = m.minute("AAPL", "2025-07-03")
prim = pd.read_parquet(RAW / "minute_2025-07-03.parquet")
prim = prim[prim["symbol"] == "AAPL"].rename(columns={"symbol": "ticker", "t": "ts"})
ref["ticker"] = "AAPL"
gaps, cst = check_cross_provider_daily(prim, ref[["ticker", "ts", "open", "high", "low", "close", "volume"]], "xval_minute_AAPL_2025-07-03", key="ts", intraday=True)
allgaps += gaps
summary["cross_provider_minute_AAPL_2025-07-03"] = {**cst, "gap_kinds": sorted(g.kind for g in gaps)}
summary["gaps"] = [g.__dict__ for g in allgaps]
(ROOT / "data" / "samples" / "alpaca_intraday_sample.summary.json").write_text(json.dumps(summary, indent=1, default=str))
print("gap kinds:", sorted({g.kind for g in allgaps}))

"""Ingest UNADJUSTED daily SIP bars from Alpaca (free) for the whole Massive security master, 2016-01-01 .. last completed session.

Resumable: one parquet part per batch under data/raw/alpaca_daily/ (git-ignored). Universe = every common stock in the master that is
active, or delisted on/after 2016-01-01, or has no delisting date (nothing is dropped because it is inconvenient). Symbols the
provider returns no bars for are RECORDED (not retried under other names, not substituted from another provider) -- the audit reads
data/raw/alpaca_daily/_requested.parquet vs the returned symbols.
"""
import hashlib
import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edgelab.alpaca import AlpacaData, MAX_SYMBOLS_PER_CALL
from edgelab.integrity import MarketCalendar

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "alpaca_daily"
OUT.mkdir(parents=True, exist_ok=True)
START = "2016-01-01"

master = pd.read_parquet(ROOT / "data" / "raw" / "massive_security_master_CS.parquet")
dl = pd.to_datetime(master.get("delisted_utc"), utc=True, errors="coerce").dt.tz_convert(None)
keep = master["active"].astype(bool) | dl.isna() | (dl >= pd.Timestamp(START))
symbols = sorted(master.loc[keep, "ticker"].dropna().unique())
pd.DataFrame({"symbol": symbols}).to_parquet(OUT / "_requested.parquet")

a = AlpacaData()
cal = MarketCalendar("US_EQUITY")
now = a.now()
last = [s for s in cal.sessions((now - pd.Timedelta(days=10)).tz_localize(None).normalize(), now.tz_localize(None).normalize()) if cal.window_utc(s)[1] < now - pd.Timedelta(hours=1)][-1]
END = (last + pd.Timedelta(days=1)).strftime("%Y-%m-%d")      # 00:00Z after the last completed session
print(f"universe={len(symbols)} symbols, window {START}..{END} (last completed session {last.date()})", flush=True)

batches = [symbols[i:i + MAX_SYMBOLS_PER_CALL] for i in range(0, len(symbols), MAX_SYMBOLS_PER_CALL)]
t0 = time.time()
for i, b in enumerate(batches):
    part = OUT / f"part-{i:05d}.parquet"
    if part.exists():
        continue
    df = a.bars(b, "1Day", START, END)
    df["session"] = df["t"].dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    df.to_parquet(part)
    print(f"batch {i + 1}/{len(batches)}: {len(df)} bars, {df['symbol'].nunique()}/{len(b)} symbols returned, {a.http.n_calls} calls, {time.time() - t0:.0f}s", flush=True)

parts = sorted(OUT.glob("part-*.parquet"))
n = sum(len(pd.read_parquet(p, columns=["symbol"])) for p in parts)
prov = {"provider": "Alpaca Market Data API (free)", "feed": "sip", "adjustment": "raw", "timeframe": "1Day", "window": [START, END],
        "requested_symbols": len(symbols), "n_parts": len(parts), "n_bars": int(n), "retrieved_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "provider_timestamp_convention": "t = 00:00 America/New_York expressed in UTC (04:00Z EDT / 05:00Z EST); 'session' column = that NY date",
        "parts_sha256": hashlib.sha256("".join(hashlib.sha256(p.read_bytes()).hexdigest() for p in parts).encode()).hexdigest(),
        "transformations": "columns renamed; session date derived from t; no filtering, filling, or symbol remapping"}
(ROOT / "data" / "samples" / "alpaca_daily_universe.provenance.json").write_text(json.dumps(prov, indent=1))
print(json.dumps({k: prov[k] for k in ("requested_symbols", "n_bars", "window")}))

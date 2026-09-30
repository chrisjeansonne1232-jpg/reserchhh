"""Pulls the Massive reference-ticker master (active + inactive/delisted common stock) into data/raw/ (git-ignored).

Nothing is filtered here; filtering (e.g. delisted since 2016) happens in the audit so the raw master stays complete.
Writes a small provenance file (committed) with counts and hash of the raw table. No credentials are written anywhere.
"""
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edgelab.massive import MassiveRest

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

m = MassiveRest()
frames = []
for active in (True, False):
    df = m.tickers(active=active)
    df["active"] = active
    print(f"active={active}: {len(df)} tickers", flush=True)
    frames.append(df)
master = pd.concat(frames, ignore_index=True)
master.to_parquet(RAW / "massive_security_master_CS.parquet")
prov = {"provider": "Massive REST (free tier)", "endpoint": "/v3/reference/tickers?market=stocks&type=CS&active={true,false}",
        "retrieved_at_utc": pd.Timestamp.now(tz="UTC").isoformat(), "n_active": int(master["active"].sum()), "n_inactive": int((~master["active"]).sum()),
        "columns": list(master.columns), "n_calls": m.http.n_calls,
        "sha256_of_sorted_ticker_active_delisted": hashlib.sha256(
            master.reindex(columns=["ticker", "active", "delisted_utc"]).astype(str).sort_values(["ticker", "active"]).to_csv(index=False).encode()).hexdigest(),
        "transformations": "none"}
(ROOT / "data" / "samples").mkdir(exist_ok=True)
(ROOT / "data" / "samples" / "massive_security_master_CS.provenance.json").write_text(json.dumps(prov, indent=1))
print(json.dumps({k: prov[k] for k in ("n_active", "n_inactive", "n_calls")}))

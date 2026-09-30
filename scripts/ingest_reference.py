"""Reference data into data/raw/ (git-ignored): Alpaca name-change events (all symbols) and Massive splits since 2016 (unfiltered, incl. future-dated).
Kept separate from the price ingest so the rename/split checks read exactly what the providers returned."""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edgelab.alpaca import AlpacaData
from edgelab.massive import MassiveRest

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)
prov = {"retrieved_at_utc": pd.Timestamp.now(tz="UTC").isoformat(), "transformations": "none"}

a = AlpacaData()
rows, tok = [], None
end = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
while True:
    d = a.http.get_json("/v1/corporate-actions", {"types": "name_change", "start": "2016-01-01", "end": end, "limit": 1000, "page_token": tok})
    rows += d["corporate_actions"].get("name_changes", [])
    tok = d.get("next_page_token")
    if not tok:
        break
ren = pd.DataFrame(rows)
ren.to_parquet(RAW / "alpaca_name_changes.parquet")
prov["alpaca_name_changes"] = {"endpoint": "/v1/corporate-actions?types=name_change", "window": ["2016-01-01", end], "n": int(len(ren)), "first_process_date": str(ren["process_date"].min())}
print("renames", len(ren), flush=True)

m = MassiveRest()
sp = m.splits(since="2016-01-01")
sp.to_parquet(RAW / "massive_splits_since_2016.parquet")
prov["massive_splits"] = {"endpoint": "/v3/reference/splits?execution_date.gte=2016-01-01", "n": int(len(sp)), "n_calls": m.http.n_calls,
                          "max_execution_date": str(sp["execution_date"].max()), "columns": list(sp.columns)}
print("splits", len(sp), flush=True)
(ROOT / "data" / "samples" / "reference.provenance.json").write_text(json.dumps(prov, indent=1))

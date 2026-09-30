"""Alpaca corporate actions 2016..: forward/reverse splits and cash dividends (all symbols) -> data/raw/ (git-ignored).
Used to (a) cross-check Massive's splits table, (b) close the 'dividends not ingested' hole. Nothing is merged; both tables are kept as returned."""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edgelab.alpaca import AlpacaData

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
a = AlpacaData()
end = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
prov = {"retrieved_at_utc": pd.Timestamp.now(tz="UTC").isoformat(), "window": ["2016-01-01", end], "transformations": "none"}
for name, types, keys in (("splits", "forward_split,reverse_split", ("forward_splits", "reverse_splits")), ("dividends", "cash_dividend", ("cash_dividends",))):
    rows, tok = [], None
    # the API bounds long windows by row count, so walk year by year
    for y in range(2016, pd.Timestamp(end).year + 1):
        tok = None
        while True:
            d = a.http.get_json("/v1/corporate-actions", {"types": types, "start": f"{y}-01-01", "end": min(end, f"{y}-12-31"), "limit": 1000, "page_token": tok})
            for k in keys:
                for r in d["corporate_actions"].get(k, []):
                    rows.append({**r, "_type": k})
            tok = d.get("next_page_token")
            if not tok:
                break
    df = pd.DataFrame(rows)
    df.to_parquet(RAW / f"alpaca_{name}.parquet")
    prov[name] = {"n": int(len(df)), "columns": list(df.columns), "types": types}
    print(name, len(df), flush=True)
(ROOT / "data" / "samples" / "alpaca_actions.provenance.json").write_text(json.dumps(prov, indent=1))

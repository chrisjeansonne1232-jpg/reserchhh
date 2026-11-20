"""Alpaca market-data client (read-only market data; no order endpoints exist in this module).

Equities use the SIP (consolidated) feed, which the free plan allows for history older than ~15 minutes.
Prices are requested RAW (unadjusted) so the cache never goes stale when a new split/dividend happens;
adjustment is applied at load time from the cached corporate-actions table (see corporate.py).
"""
from __future__ import annotations

import pandas as pd

from .config import ALPACA_DATA_URL, get_secret
from .http import Http
from .ratelimit import RateLimiter

TIMEFRAMES = {"1d": "1Day", "1h": "1Hour", "15m": "15Min", "5m": "5Min", "1m": "1Min"}
_COLS = {"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "n": "trade_count", "vw": "vwap"}


def _frame(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=list(_COLS.values()), index=pd.DatetimeIndex([], tz="UTC", name="ts"))
    df = pd.DataFrame(rows)
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("t"), utc=True), name="ts")
    df = df.rename(columns=_COLS)[list(_COLS.values())].astype("float64")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def _iso(x) -> str:
    return pd.Timestamp(x).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ") if pd.Timestamp(x).tzinfo else \
        pd.Timestamp(x).tz_localize("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


class AlpacaData:
    def __init__(self, http: Http | None = None, feed: str = "sip"):
        self.feed = feed
        self.http = http or Http({"APCA-API-KEY-ID": get_secret("alpaca_key"),
                                  "APCA-API-SECRET-KEY": get_secret("alpaca_secret")},
                                 RateLimiter(150, 60))   # free plan allows 200/min; stay under

    def _bars(self, path: str, symbols: list[str], tf: str, start, end, extra: dict) -> dict[str, pd.DataFrame]:
        params = {"symbols": ",".join(symbols), "timeframe": TIMEFRAMES[tf], "start": _iso(start), "end": _iso(end),
                  "limit": 10000, "sort": "asc", **extra}
        rows: dict[str, list] = {s: [] for s in symbols}
        while True:
            j = self.http.get_json(f"{ALPACA_DATA_URL}{path}", params)
            for s, lst in (j.get("bars") or {}).items():
                rows.setdefault(s, []).extend(lst)
            tok = j.get("next_page_token")
            if not tok:
                break
            params["page_token"] = tok
        return {s: _frame(r) for s, r in rows.items()}

    def stock_bars(self, symbols: list[str], tf: str, start, end) -> dict[str, pd.DataFrame]:
        return self._bars("/v2/stocks/bars", symbols, tf, start, end, {"adjustment": "raw", "feed": self.feed})

    def stock_bars_adjusted_reference(self, symbol: str, tf: str, start, end, adjustment: str = "split") -> pd.DataFrame:
        """Provider-adjusted bars. NOT cached or used for research: only to cross-check OUR adjustment code."""
        return self._bars("/v2/stocks/bars", [symbol], tf, start, end, {"adjustment": adjustment, "feed": self.feed})[symbol]

    def crypto_bars(self, symbols: list[str], tf: str, start, end) -> dict[str, pd.DataFrame]:
        return self._bars("/v1beta3/crypto/us/bars", symbols, tf, start, end, {})

    def corporate_actions(self, symbols: list[str], start="2015-01-01", end=None) -> pd.DataFrame:
        """Splits and cash dividends -> columns: symbol, ex_date, kind ('split'|'dividend'), ratio, rate."""
        end = end or (pd.Timestamp.now("UTC") + pd.Timedelta(days=60))
        params = {"symbols": ",".join(symbols), "types": "forward_split,reverse_split,cash_dividend",
                  "start": pd.Timestamp(start).strftime("%Y-%m-%d"), "end": pd.Timestamp(end).strftime("%Y-%m-%d"),
                  "limit": 1000}
        out = []
        while True:
            j = self.http.get_json(f"{ALPACA_DATA_URL}/v1/corporate-actions", params)
            ca = j.get("corporate_actions") or {}
            for k in ("forward_splits", "reverse_splits"):
                for x in ca.get(k, []):
                    # new_rate/old_rate: 4/1 forward split => price x 1/4. reverse 1/10 => price x 10.
                    out.append((x["symbol"], x["ex_date"], "split", float(x["new_rate"]) / float(x["old_rate"]), 0.0))
            for x in ca.get("cash_dividends", []):
                out.append((x["symbol"], x["ex_date"], "dividend", 1.0, float(x["rate"])))
            tok = j.get("next_page_token")
            if not tok:
                break
            params["page_token"] = tok
        df = pd.DataFrame(out, columns=["symbol", "ex_date", "kind", "ratio", "rate"])
        df["ex_date"] = pd.to_datetime(df["ex_date"])
        return df.drop_duplicates().sort_values(["symbol", "ex_date", "kind"]).reset_index(drop=True)

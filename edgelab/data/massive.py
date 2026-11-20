"""Massive (formerly Polygon) client. Free tier: ~5 calls/min and ~2 years of history, so it is used as an
independent second source to cross-check Alpaca, not as the primary price source."""
from __future__ import annotations

import pandas as pd

from .config import MASSIVE_URL, get_secret
from .http import Http
from .ratelimit import RateLimiter

_SPAN = {"1d": (1, "day"), "1h": (1, "hour"), "15m": (15, "minute"), "5m": (5, "minute"), "1m": (1, "minute")}


class MassiveData:
    def __init__(self, http: Http | None = None):
        self.http = http or Http({"Authorization": "Bearer " + get_secret("massive_key")}, RateLimiter(5, 62))

    def aggregates(self, symbol: str, tf: str, start, end, adjusted: bool = False) -> pd.DataFrame:
        mult, span = _SPAN[tf]
        s, e = pd.Timestamp(start).strftime("%Y-%m-%d"), pd.Timestamp(end).strftime("%Y-%m-%d")
        url = f"{MASSIVE_URL}/v2/aggs/ticker/{symbol}/range/{mult}/{span}/{s}/{e}"
        params = {"adjusted": str(adjusted).lower(), "sort": "asc", "limit": 50000}
        rows = []
        while url:
            j = self.http.get_json(url, params)
            rows.extend(j.get("results") or [])
            url, params = j.get("next_url"), None   # next_url already carries its query string
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"],
                                index=pd.DatetimeIndex([], tz="UTC", name="ts"))
        df = pd.DataFrame(rows)
        df.index = pd.DatetimeIndex(pd.to_datetime(df["t"], unit="ms", utc=True), name="ts")
        df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        return df[["open", "high", "low", "close", "volume"]].astype("float64")[lambda d: ~d.index.duplicated()].sort_index()

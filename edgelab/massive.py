"""Massive REST client (free tier) -- reference data, splits, and CROSS-VALIDATION of Alpaca prices only.

Free tier measured 2026-09-30: 5 requests/minute; aggregates entitled for roughly the last 2 years only
(2016 -> HTTP 403 NOT_AUTHORIZED). It is therefore never used as a price source for the research history.
Auth is the Authorization header (never the ?apiKey= query string) so the key cannot leak into URLs or logs.
"""
from __future__ import annotations

import pandas as pd

from .providers import HttpClient, require_env

BASE = "https://api.massive.com"


class MassiveRest:
    def __init__(self, calls_per_minute: float = 4.5):
        env = require_env("MASSIVE_API_KEY")
        self.http = HttpClient(BASE, {"Authorization": "Bearer " + env["MASSIVE_API_KEY"]}, list(env.values()), calls_per_minute)

    def _follow(self, path: str, params: dict, max_pages: int | None = None) -> list[dict]:
        out, url, p, pages = [], path, params, 0
        while url:
            d = self.http.get_json(url, p)
            out += d.get("results") or []
            url, p, pages = d.get("next_url"), None, pages + 1
            if max_pages and pages >= max_pages:
                break
        return out

    def tickers(self, active: bool, type_: str = "CS", max_pages: int | None = None) -> pd.DataFrame:
        rows = self._follow("/v3/reference/tickers", {"market": "stocks", "type": type_, "active": str(active).lower(), "limit": 1000, "sort": "ticker"}, max_pages)
        return pd.DataFrame(rows)

    def splits(self, ticker: str | None = None, since: str | None = None, max_pages: int | None = None) -> pd.DataFrame:
        """All splits (optionally from `since`, by execution_date). NOT point-in-time as returned: includes future-dated actions."""
        rows = self._follow("/v3/reference/splits", {"ticker": ticker, "execution_date.gte": since, "limit": 1000, "sort": "execution_date"}, max_pages)
        return pd.DataFrame(rows)

    def daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """Unadjusted daily aggregates. t is midnight America/New_York (epoch ms)."""
        d = self.http.get_json(f"/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}", {"adjusted": "false", "limit": 50000})
        df = pd.DataFrame(d.get("results") or [], columns=["t", "o", "h", "l", "c", "v", "vw", "n"])
        df["date"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
        return df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "n": "trades"}).drop(columns=["t"])

    def minute(self, ticker: str, day: str) -> pd.DataFrame:
        """Unadjusted 1-minute aggregates for one calendar day; ts = window start (UTC)."""
        d = self.http.get_json(f"/v2/aggs/ticker/{ticker}/range/1/minute/{day}/{day}", {"adjusted": "false", "limit": 50000})
        df = pd.DataFrame(d.get("results") or [], columns=["t", "o", "h", "l", "c", "v", "vw", "n"])
        df["ts"] = pd.to_datetime(df["t"], unit="ms", utc=True)
        return df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "n": "trades"}).drop(columns=["t"])

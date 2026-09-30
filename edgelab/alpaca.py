"""Alpaca free Market Data API (SIP feed, historical only) -- PRIMARY price source.

Facts measured against the live free tier (2026-09-30, see docs/DATA_INTEGRITY_REPORT.md):
  * feed=sip works for daily/minute bars, trades and quotes from 2016-01 onward; requests whose end is inside the last
    ~15 minutes are refused by the provider (HTTP 403). We refuse them first, loudly, instead of clipping the window.
  * 200 requests/minute. We pace at 150/min.
  * history is keyed by the CURRENT symbol (asking for META in 2016 returns Facebook; FB returns nothing) -> see
    edgelab.integrity.check_ticker_renames. Never treat a returned symbol as the point-in-time ticker.
  * adjustment is always requested as 'raw' so splits stay visible and are checked against the splits table.
"""
from __future__ import annotations

import pandas as pd

from .providers import HttpClient, ProviderError, RecentDataRefused, require_env

DATA_BASE = "https://data.alpaca.markets"
EMBARGO_MIN = 16          # provider rule is 15 min; one minute of margin for clock skew
EARLIEST = pd.Timestamp("2016-01-01", tz="UTC")
MAX_SYMBOLS_PER_CALL = 100


def _ts(x) -> pd.Timestamp:
    t = pd.Timestamp(x)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


class AlpacaData:
    def __init__(self, calls_per_minute: float = 150, now=None):
        env = require_env("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY")
        self.http = HttpClient(DATA_BASE, {"APCA-API-KEY-ID": env["ALPACA_API_KEY_ID"], "APCA-API-SECRET-KEY": env["ALPACA_API_SECRET_KEY"]},
                               list(env.values()), calls_per_minute)
        self._now = now

    def now(self) -> pd.Timestamp:
        return _ts(self._now) if self._now is not None else pd.Timestamp.now(tz="UTC")

    def _window(self, start, end) -> tuple[str, str]:
        s, e = _ts(start), _ts(end)
        if s < EARLIEST:
            raise ProviderError(f"start {s.date()} precedes the supported history ({EARLIEST.date()})")
        if e > self.now() - pd.Timedelta(minutes=EMBARGO_MIN):
            raise RecentDataRefused(f"end {e.isoformat()} is inside the {EMBARGO_MIN}-minute SIP embargo; free tier is historical-only")
        if s >= e:
            raise ProviderError("empty window")
        return s.strftime("%Y-%m-%dT%H:%M:%SZ"), e.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _paged(self, path: str, key: str, symbols: list[str], params: dict) -> dict[str, list[dict]]:
        if len(symbols) > MAX_SYMBOLS_PER_CALL:
            raise ProviderError(f"at most {MAX_SYMBOLS_PER_CALL} symbols per call")
        out: dict[str, list[dict]] = {}
        token = None
        while True:
            d = self.http.get_json(path, {**params, "symbols": ",".join(symbols), "feed": "sip", "page_token": token})
            for sym, rows in (d.get(key) or {}).items():
                out.setdefault(sym, []).extend(rows)
            token = d.get("next_page_token")
            if not token:
                return out

    # ---------------------------------------------------------------- bars
    def bars(self, symbols: list[str], timeframe: str, start, end, limit: int = 10000) -> pd.DataFrame:
        """timeframe '1Day' or '1Min'. Returns columns [symbol, t (UTC), open, high, low, close, volume, vwap, trades]."""
        s, e = self._window(start, end)
        raw = self._paged("/v2/stocks/bars", "bars", symbols,
                          {"timeframe": timeframe, "start": s, "end": e, "adjustment": "raw", "limit": limit, "sort": "asc"})
        rows = [{"symbol": sym, **r} for sym, rs in raw.items() for r in rs]
        df = pd.DataFrame(rows, columns=["symbol", "t", "o", "h", "l", "c", "v", "vw", "n"])
        df["t"] = pd.to_datetime(df["t"], utc=True, format="ISO8601")
        return df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "vw": "vwap", "n": "trades"})

    # ---------------------------------------------------------------- ticks
    def trades(self, symbol: str, start, end, limit: int = 10000, max_rows: int | None = None) -> pd.DataFrame:
        s, e = self._window(start, end)
        rows, token = [], None
        while True:
            d = self.http.get_json("/v2/stocks/trades", {"symbols": symbol, "start": s, "end": e, "feed": "sip", "limit": limit, "page_token": token})
            rows += (d.get("trades") or {}).get(symbol, [])
            token = d.get("next_page_token")
            if not token or (max_rows and len(rows) >= max_rows):
                break
        df = pd.DataFrame(rows, columns=["t", "x", "p", "s", "c", "i", "z"])
        df["t"] = pd.to_datetime(df["t"], utc=True, format="ISO8601")
        return df.rename(columns={"x": "exchange", "p": "price", "s": "size", "c": "conditions", "i": "trade_id", "z": "tape"})

    def quotes(self, symbol: str, start, end, limit: int = 10000, max_rows: int | None = None) -> pd.DataFrame:
        s, e = self._window(start, end)
        rows, token = [], None
        while True:
            d = self.http.get_json("/v2/stocks/quotes", {"symbols": symbol, "start": s, "end": e, "feed": "sip", "limit": limit, "page_token": token})
            rows += (d.get("quotes") or {}).get(symbol, [])
            token = d.get("next_page_token")
            if not token or (max_rows and len(rows) >= max_rows):
                break
        df = pd.DataFrame(rows, columns=["t", "ax", "ap", "as", "bx", "bp", "bs", "c", "z"])
        df["t"] = pd.to_datetime(df["t"], utc=True, format="ISO8601")
        return df.rename(columns={"ax": "ask_exchange", "ap": "ask", "as": "ask_size", "bx": "bid_exchange", "bp": "bid", "bs": "bid_size", "c": "conditions", "z": "tape"})

    # ---------------------------------------------------------------- corporate actions (renames, splits)
    def corporate_actions(self, symbols: list[str], types: list[str], start, end) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        token = None
        while True:
            d = self.http.get_json("/v1/corporate-actions", {"symbols": ",".join(symbols), "types": ",".join(types),
                                                             "start": pd.Timestamp(start).strftime("%Y-%m-%d"), "end": pd.Timestamp(end).strftime("%Y-%m-%d"),
                                                             "limit": 1000, "page_token": token})
            for k, rows in (d.get("corporate_actions") or {}).items():
                out.setdefault(k, []).extend(rows)
            token = d.get("next_page_token")
            if not token:
                return out

"""Incremental downloader: asks the provider only for ranges the cache does not already cover."""
from __future__ import annotations

import pandas as pd

from .alpaca import AlpacaData
from .cache import BarCache

ET = "America/New_York"
BATCH = {"1d": 20, "1h": 10, "15m": 5, "5m": 3, "1m": 1}      # symbols per request (keeps pages / memory sane)
CHUNK_DAYS = {"1d": 4000, "1h": 730, "15m": 365, "5m": 365, "1m": 90}   # one write (= one resume point) per chunk
CRYPTO_START = pd.Timestamp("2021-01-01", tz="UTC")             # Alpaca crypto history begins ~2021


def is_crypto(symbol: str) -> bool:
    return "/" in symbol


def safe_end(now: pd.Timestamp | None = None) -> pd.Timestamp:
    """Midnight New York today, in UTC. Everything before it is a finished session; today's partial bars are
    never cached (they would be incomplete and the free SIP plan blocks the last ~15 minutes anyway)."""
    now = now or pd.Timestamp.now("UTC")
    return now.tz_convert(ET).normalize().tz_convert("UTC")


def chunks(rng: tuple[pd.Timestamp, pd.Timestamp], days: int):
    s, e = rng
    step = pd.Timedelta(days=days)
    while s < e:
        yield s, min(s + step, e)
        s = s + step


class Downloader:
    def __init__(self, alpaca: AlpacaData, cache: BarCache | None = None, log=print):
        self.alpaca, self.cache, self.log = alpaca, cache or BarCache(), log

    def sync(self, symbols: list[str], tf: str, start, end=None) -> dict[str, int]:
        """Make the cache cover [start, end) for every symbol. Returns {symbol: new_rows_downloaded}."""
        start = pd.Timestamp(start, tz="UTC") if pd.Timestamp(start).tzinfo is None else pd.Timestamp(start).tz_convert("UTC")
        end = min(pd.Timestamp(end).tz_convert("UTC") if end is not None and pd.Timestamp(end).tzinfo else
                  (pd.Timestamp(end, tz="UTC") if end is not None else safe_end()), safe_end())
        feed = self.alpaca.feed
        plan: dict[tuple, list[str]] = {}
        for s in symbols:
            st = max(start, CRYPTO_START) if is_crypto(s) else start
            miss = self.cache.missing("alpaca", feed if not is_crypto(s) else "crypto", tf, s, st, end)
            if miss:
                plan.setdefault(tuple(miss), []).append(s)
        added = {s: 0 for s in symbols}
        if not plan:
            self.log(f"[{tf}] cache already covers everything requested -- nothing to download")
        for miss, syms in plan.items():
            for rng in miss:
                for a, b in chunks(rng, CHUNK_DAYS[tf]):
                    for kind, group in (("stock", [s for s in syms if not is_crypto(s)]), ("crypto", [s for s in syms if is_crypto(s)])):
                        for i in range(0, len(group), BATCH[tf]):
                            batch = group[i:i + BATCH[tf]]
                            got = (self.alpaca.stock_bars if kind == "stock" else self.alpaca.crypto_bars)(batch, tf, a, b)
                            for s in batch:
                                df = got.get(s)
                                df = df if df is not None else pd.DataFrame()
                                self.cache.write("alpaca", feed if kind == "stock" else "crypto", tf, s, df, (a, b))
                                added[s] += len(df)
                            self.log(f"[{tf}] {a.date()}..{b.date()} {', '.join(batch)}: "
                                     f"{sum(len(got.get(s, [])) for s in batch)} rows")
        return added

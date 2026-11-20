"""Parquet bar cache with coverage tracking, so a date range is never downloaded twice.

Layout:  data/cache/<provider>/<feed>/<timeframe>/<SYMBOL>.parquet  (+ .meta.json sidecar)
The sidecar lists `coverage`: [start, end) ranges that have been REQUESTED and fully received, including
ranges that returned no rows (holidays, before listing) -- those must not be re-requested either.
Writes are atomic (temp file + os.replace) so a crash or reboot cannot leave a half-written file.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pandas as pd

from .config import CACHE_DIR

Range = tuple[pd.Timestamp, pd.Timestamp]


def _merge(ranges: list[Range]) -> list[Range]:
    out: list[Range] = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def subtract(want: Range, have: list[Range]) -> list[Range]:
    """Parts of `want` not covered by `have`."""
    out, cur = [], want[0]
    for s, e in _merge(have):
        if e <= cur:
            continue
        if s >= want[1]:
            break
        if s > cur:
            out.append((cur, s))
        cur = max(cur, e)
    if cur < want[1]:
        out.append((cur, want[1]))
    return out


def _atomic_write(path: Path, writer) -> None:
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    writer(tmp)
    os.replace(tmp, path)


class BarCache:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else CACHE_DIR

    def path(self, provider: str, feed: str, tf: str, symbol: str) -> Path:
        return self.root / provider / feed / tf / (symbol.replace("/", "-") + ".parquet")

    def _meta_path(self, p: Path) -> Path:
        return p.with_suffix(".meta.json")

    def read(self, provider, feed, tf, symbol) -> pd.DataFrame | None:
        p = self.path(provider, feed, tf, symbol)
        return pd.read_parquet(p) if p.exists() else None

    def coverage(self, provider, feed, tf, symbol) -> list[Range]:
        m = self._meta_path(self.path(provider, feed, tf, symbol))
        if not m.exists():
            return []
        meta = json.loads(m.read_text())
        return [(pd.Timestamp(a), pd.Timestamp(b)) for a, b in meta.get("coverage", [])]

    def missing(self, provider, feed, tf, symbol, start, end) -> list[Range]:
        want = (pd.Timestamp(start).tz_convert("UTC"), pd.Timestamp(end).tz_convert("UTC"))
        if want[0] >= want[1]:
            return []
        return subtract(want, self.coverage(provider, feed, tf, symbol))

    def write(self, provider, feed, tf, symbol, new: pd.DataFrame, fetched: Range, extra_meta: dict | None = None) -> None:
        """Merge `new` rows into the cache and record that `fetched` was fully requested."""
        p = self.path(provider, feed, tf, symbol)
        p.parent.mkdir(parents=True, exist_ok=True)
        old = self.read(provider, feed, tf, symbol)
        df = new if old is None or old.empty else pd.concat([old, new]) if not new.empty else old
        df = df[~df.index.duplicated(keep="last")].sort_index()
        cov = _merge(self.coverage(provider, feed, tf, symbol) + [fetched])
        _atomic_write(p, lambda t: df.to_parquet(t, compression="zstd"))
        meta = {"provider": provider, "feed": feed, "timeframe": tf, "symbol": symbol, "adjustment": "raw",
                "coverage": [[a.isoformat(), b.isoformat()] for a, b in cov], "rows": int(len(df)),
                "first_bar": None if df.empty else df.index[0].isoformat(),
                "last_bar": None if df.empty else df.index[-1].isoformat(),
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                "updated_utc": pd.Timestamp.now("UTC").isoformat(), **(extra_meta or {})}
        _atomic_write(self._meta_path(p), lambda t: t.write_text(json.dumps(meta, indent=1)))

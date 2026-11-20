"""Universe: S&P 500 + Nasdaq-100 components (from Wikipedia tables) + core ETFs + BTC/ETH.

Membership is the CURRENT list -> survivorship bias (see quality.SURVIVORSHIP_NOTE). The snapshot is cached with
its fetch date so a research run can state exactly which list it used.
"""
from __future__ import annotations

import io
import json

import pandas as pd
import requests

from .config import CACHE_DIR
from .quality import SURVIVORSHIP_NOTE

UA = "EdgeLabResearch/0.1 (personal backtesting research; python-requests)"
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NDX_URL = "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies"
CORE_ETFS = ["SPY", "QQQ", "IWM"]
CRYPTO = ["BTC/USD", "ETH/USD"]


def _tables(html: str) -> list[pd.DataFrame]:
    return pd.read_html(io.StringIO(html))


def _pick(tables: list[pd.DataFrame], col_candidates: tuple[str, ...], min_rows: int) -> pd.Series:
    for t in tables:
        cols = {str(c).strip().lower(): c for c in t.columns}
        for cand in col_candidates:
            if cand in cols and len(t) >= min_rows:
                s = t[cols[cand]].astype(str).str.strip().str.upper().str.replace(r"\s+", "", regex=True)
                return s[s.str.fullmatch(r"[A-Z][A-Z0-9.\-]{0,6}")].drop_duplicates().reset_index(drop=True)
    raise ValueError(f"no table with a column in {col_candidates} and >= {min_rows} rows found")


def parse_sp500(html: str) -> list[str]:
    return list(_pick(_tables(html), ("symbol", "ticker"), 400))


def parse_ndx(html: str) -> list[str]:
    return list(_pick(_tables(html), ("ticker", "symbol"), 80))


def _get(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    return r.text


def build_universe(path=None) -> dict:
    sp, nd = parse_sp500(_get(SP500_URL)), parse_ndx(_get(NDX_URL))
    comps = sorted(set(sp) | set(nd))
    uni = {"fetched_utc": pd.Timestamp.now("UTC").isoformat(), "sources": [SP500_URL, NDX_URL],
           "sp500": sp, "ndx100": nd, "components": comps, "etfs": CORE_ETFS, "crypto": CRYPTO,
           "survivorship_note": SURVIVORSHIP_NOTE}
    p = path or (CACHE_DIR / "universe" / "universe_latest.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(uni, indent=1))
    return uni


def load_universe(path=None) -> dict:
    p = path or (CACHE_DIR / "universe" / "universe_latest.json")
    if not p.exists():
        raise FileNotFoundError("no universe snapshot yet; run: python -m edgelab.data universe")
    return json.loads(p.read_text())

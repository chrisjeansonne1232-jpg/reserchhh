"""Paths, provider URLs and API-key lookup.

Keys are read from environment variables ONLY. Nothing here ever returns a key to a caller that
could print it by accident: `key_status()` reports variable *names*, never values.
PAPER TRADING ONLY: `assert_paper_url` refuses anything that is not Alpaca's paper endpoint.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(os.environ.get("EDGELAB_HOME", Path(__file__).resolve().parents[2]))
CACHE_DIR = ROOT / "data" / "cache"
ALPACA_DATA_URL = "https://data.alpaca.markets"
ALPACA_PAPER_URL = "https://paper-api.alpaca.markets"
MASSIVE_URL = "https://api.massive.com"

# first name found wins; extra aliases so a differently-named variable on your PC still works
_ALIASES = {
    "alpaca_key": ["ALPACA_API_KEY_ID", "APCA_API_KEY_ID", "ALPACA_API_KEY", "ALPACA_KEY_ID"],
    "alpaca_secret": ["ALPACA_API_SECRET_KEY", "APCA_API_SECRET_KEY", "ALPACA_SECRET_KEY", "ALPACA_API_SECRET"],
    "massive_key": ["MASSIVE_API_KEY", "POLYGON_API_KEY"],
}


class MissingKey(RuntimeError):
    pass


class LiveTradingForbidden(RuntimeError):
    pass


def _find(kind: str) -> tuple[str | None, str | None]:
    for name in _ALIASES[kind]:
        v = os.environ.get(name, "").strip()
        if v:
            return name, v
    return None, None


def get_secret(kind: str) -> str:
    name, v = _find(kind)
    if v is None:
        raise MissingKey(f"no environment variable found for '{kind}'. Looked for: {', '.join(_ALIASES[kind])}")
    return v


def key_status() -> dict[str, str]:
    """{'alpaca_key': 'found in ALPACA_API_KEY_ID', ...} -- names only, never values."""
    out = {}
    for kind in _ALIASES:
        name, _ = _find(kind)
        out[kind] = f"found in {name}" if name else "NOT FOUND (looked for " + ", ".join(_ALIASES[kind]) + ")"
    return out


def assert_paper_url(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host != "paper-api.alpaca.markets":
        raise LiveTradingForbidden(f"refusing to use '{host}': Edge Lab is PAPER-ONLY (allowed trading host: paper-api.alpaca.markets)")
    return url

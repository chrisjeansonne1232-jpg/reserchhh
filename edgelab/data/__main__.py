"""Command line:  python -m edgelab.data <command>

  keys                         which API-key environment variables were found (names only, never values)
  probe                        what your free plans actually allow (history depth per timeframe)
  universe                     fetch/cache the S&P 500 + Nasdaq-100 component list
  download  --symbols ... --tf 1d 15m ... [--start 2016-01-01]    (or --tier core|components-daily)
  check     --symbols ... --tf ...      data-quality report for cached data
  crosscheck --symbols SPY ...          Alpaca vs Massive on their overlapping window (last ~2 years)
  status                                what is in the cache
  freeze-holdout                        one-time: seal the most recent 20% of history for the final test
"""
from __future__ import annotations

import argparse
import json
import sys

import pandas as pd

from . import config
from .cache import BarCache
from .corporate import CorporateActionsStore
from .downloader import Downloader, is_crypto, safe_end
from .loader import load_bars
from .quality import check_bars, cross_check

START = "2016-01-01"      # Alpaca SIP history floor on the free plan (probed)


def _symbols(a) -> list[str]:
    from .universe import CORE_ETFS, CRYPTO, load_universe
    if a.tier == "core":
        return CORE_ETFS + CRYPTO
    if a.tier == "components-daily":
        return CORE_ETFS + load_universe()["components"] + CRYPTO
    return a.symbols


def cmd_keys(a):
    for k, v in config.key_status().items():
        print(f"{k:14s} {v}")


def cmd_probe(a):
    from .alpaca import AlpacaData
    from .massive import MassiveData
    al = AlpacaData()
    print("ALPACA (SIP, SPY) -- earliest bars available on your plan:")
    for tf, s, e in [("1d", "2010-01-04", "2010-03-01"), ("1d", START, "2016-03-01"), ("1h", START, "2016-01-20"),
                     ("15m", START, "2016-01-12"), ("5m", START, "2016-01-12"), ("1m", "2020-01-02", "2020-01-04")]:
        n = len(al.stock_bars(["SPY"], tf, pd.Timestamp(s, tz="UTC"), pd.Timestamp(e, tz="UTC"))["SPY"])
        print(f"  {tf:>3s} from {s}: {n} bars")
    try:
        n = len(al.crypto_bars(["BTC/USD"], "1d", pd.Timestamp("2021-01-01", tz="UTC"), pd.Timestamp("2021-02-01", tz="UTC"))["BTC/USD"])
        print(f"  crypto BTC/USD 1d from 2021-01-01: {n} bars")
    except Exception as e:  # noqa: BLE001
        print("  crypto:", e)
    print("MASSIVE (free tier) -- depth:")
    m = MassiveData()
    for label, s, e in [("2025", "2025-06-02", "2025-06-06"), ("2024-12", "2024-12-02", "2024-12-06"), ("2023", "2023-06-01", "2023-06-09")]:
        try:
            print(f"  daily {label}: {len(m.aggregates('SPY', '1d', s, e))} bars")
        except Exception as ex:  # noqa: BLE001
            print(f"  daily {label}: not available ({str(ex)[:70]})")


def cmd_universe(a):
    from .universe import build_universe
    u = build_universe()
    print(f"S&P 500: {len(u['sp500'])}  Nasdaq-100: {len(u['ndx100'])}  unique components: {len(u['components'])}")
    print("NOTE:", u["survivorship_note"])


def cmd_download(a):
    from .alpaca import AlpacaData
    al = AlpacaData()
    syms = _symbols(a)
    dl = Downloader(al)
    tfs = a.tf or ["1d"]
    eq, cr = [s for s in syms if not is_crypto(s)], [s for s in syms if is_crypto(s)]
    if eq:
        CorporateActionsStore().refresh(al, eq, log=print)
    for tf in tfs:
        if tf == "1h":      # equity 1h is built from 15m (see loader); crypto 1h is native
            if eq:
                dl.sync(eq, "15m", a.start)
            if cr:
                dl.sync(cr, "1h", a.start)
        else:
            dl.sync(syms, tf, a.start)
    print("done. Data is cached; re-running only downloads what is missing.")


def cmd_check(a):
    bad = 0
    for s in _symbols(a):
        for tf in a.tf or ["1d"]:
            try:
                df = load_bars(s, tf, adjust="total")
            except FileNotFoundError as e:
                print(e)
                continue
            rep = check_bars(df, s, tf, crypto=is_crypto(s))
            print(rep.summary())
            bad += not rep.ok
            out = config.CACHE_DIR / "_quality"
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{s.replace('/', '-')}_{tf}.json").write_text(json.dumps(rep.to_dict(), indent=1))
    sys.exit(1 if bad else 0)


def cmd_crosscheck(a):
    from .massive import MassiveData
    m, cache = MassiveData(), BarCache()
    end = safe_end()
    start = end - pd.Timedelta(days=700)
    for s in a.symbols:
        for tf in a.tf or ["1d"]:
            prim = load_bars(s, tf, start, end, adjust="raw", session="all" if tf == "1d" else "rth")
            sec = m.aggregates(s, tf, start, end, adjusted=False)
            if tf == "1d":      # normalise both to the session date: providers stamp daily bars differently
                prim.index = prim.index.tz_convert("America/New_York").tz_localize(None).normalize()
                sec.index = sec.index.tz_convert("America/New_York").tz_localize(None).normalize()
            print(s, tf, json.dumps(cross_check(prim, sec)))


def cmd_freeze_holdout(a):
    from .holdout import freeze_holdout
    meta = freeze_holdout(load_bars("SPY", "1d", adjust="raw").index)
    print("Holdout frozen. Research data ends before", meta["holdout_start_utc"][:10], "- everything from that date on is sealed.")


def cmd_status(a):
    root = BarCache().root
    metas = sorted(root.rglob("*.meta.json"))
    print(f"cache: {root}  ({len(metas)} series)")
    for m in metas[:200]:
        j = json.loads(m.read_text())
        if "symbol" in j:
            print(f"  {j['provider']}/{j['feed']}/{j['timeframe']}/{j['symbol']}: {j['rows']} rows {str(j['first_bar'])[:10]}..{str(j['last_bar'])[:10]}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m edgelab.data", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in [("keys", cmd_keys), ("probe", cmd_probe), ("universe", cmd_universe), ("download", cmd_download),
                     ("check", cmd_check), ("crosscheck", cmd_crosscheck), ("status", cmd_status),
                     ("freeze-holdout", cmd_freeze_holdout)]:
        sp = sub.add_parser(name)
        sp.add_argument("--symbols", nargs="+", default=["SPY"])
        sp.add_argument("--tf", nargs="+", choices=["1d", "1h", "15m", "5m", "1m"])
        sp.add_argument("--start", default=START)
        sp.add_argument("--tier", choices=["core", "components-daily"])
        sp.set_defaults(fn=fn)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()

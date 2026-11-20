"""Data layer tests (offline: fake providers, synthetic bars)."""
import json

import numpy as np
import pandas as pd
import pytest

from edgelab.data import config
from edgelab.data.cache import BarCache, subtract
from edgelab.data.corporate import adjust_bars
from edgelab.data.downloader import Downloader, safe_end
from edgelab.data.http import Http, ProviderError
from edgelab.data.loader import resample_rth, rth_filter
from edgelab.data.quality import check_bars, cross_check
from edgelab.data.ratelimit import RateLimiter
from edgelab.data.universe import parse_ndx, parse_sp500

T = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731


# ------------------------------------------------------------------ safety / keys
def test_key_status_reports_names_not_values(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "SECRETVALUE123")
    out = json.dumps(config.key_status())
    assert "ALPACA_API_KEY_ID" in out and "SECRETVALUE123" not in out


def test_missing_key_raises_clear_error(monkeypatch):
    for n in config._ALIASES["massive_key"]:
        monkeypatch.delenv(n, raising=False)
    with pytest.raises(config.MissingKey):
        config.get_secret("massive_key")


def test_only_the_paper_trading_host_is_allowed():
    assert config.assert_paper_url("https://paper-api.alpaca.markets/v2/account")
    for bad in ("https://api.alpaca.markets/v2/orders", "https://evil.example.com", "https://paper-api.alpaca.markets.evil.com/x"):
        with pytest.raises(config.LiveTradingForbidden):
            config.assert_paper_url(bad)


def test_no_order_endpoints_exist_in_data_clients():
    import inspect

    from edgelab.data import alpaca, massive
    src = inspect.getsource(alpaca) + inspect.getsource(massive)
    assert "/v2/orders" not in src and ".post(" not in src


# ------------------------------------------------------------------ rate limit / http
def test_rate_limiter_blocks_the_sixth_call_in_a_window():
    now = [0.0]
    slept = []
    rl = RateLimiter(5, 60, clock=lambda: now[0], sleep=lambda d: (slept.append(d), now.__setitem__(0, now[0] + d)))
    for _ in range(5):
        rl.wait()
    assert slept == []
    rl.wait()
    assert len(slept) == 1 and slept[0] >= 59.9


class FakeResp:
    def __init__(self, code, body=None, headers=None):
        self.status_code, self._b, self.headers, self.text = code, body or {}, headers or {}, json.dumps(body or {})

    def json(self):
        return self._b


class FakeSession:
    def __init__(self, codes):
        self.codes, self.calls = list(codes), 0

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls += 1
        c = self.codes.pop(0)
        return FakeResp(c, {"ok": True} if c == 200 else {"err": "x"})


def test_http_retries_429_then_succeeds_and_does_not_retry_403():
    sleeps = []
    h = Http({}, RateLimiter(1000, 1), session=FakeSession([429, 500, 200]), sleep=sleeps.append)
    assert h.get_json("http://x") == {"ok": True} and len(sleeps) == 2
    h2 = Http({}, RateLimiter(1000, 1), session=FakeSession([403, 200]), sleep=sleeps.append)
    with pytest.raises(ProviderError) as e:
        h2.get_json("http://x")
    assert e.value.status == 403 and h2.session.calls == 1


# ------------------------------------------------------------------ cache coverage
def test_subtract_ranges():
    w = (T("2020-01-01"), T("2020-12-31"))
    have = [(T("2020-03-01"), T("2020-06-01")), (T("2020-05-01"), T("2020-07-01"))]
    assert subtract(w, have) == [(T("2020-01-01"), T("2020-03-01")), (T("2020-07-01"), T("2020-12-31"))]
    assert subtract(w, [w]) == []


def fake_bars(start, end, tf="1d"):
    idx = pd.date_range(start, end, freq="B", tz="UTC", inclusive="left")
    n = len(idx)
    return pd.DataFrame({"open": np.arange(n) + 100.0, "high": np.arange(n) + 101.0, "low": np.arange(n) + 99.0,
                         "close": np.arange(n) + 100.5, "volume": 1e6, "trade_count": 1e3, "vwap": 100.0}, index=pd.DatetimeIndex(idx, name="ts"))


class FakeAlpaca:
    feed = "sip"

    def __init__(self):
        self.calls = []

    def stock_bars(self, symbols, tf, a, b):
        self.calls.append((tuple(symbols), tf, a, b))
        return {s: fake_bars(a, b) for s in symbols}

    crypto_bars = stock_bars


def test_downloader_never_fetches_the_same_range_twice(tmp_path):
    cache, al = BarCache(tmp_path), FakeAlpaca()
    dl = Downloader(al, cache, log=lambda s: None)
    dl.sync(["SPY", "QQQ"], "1d", "2020-01-01", "2021-01-01")
    n1 = len(al.calls)
    assert n1 >= 1
    dl.sync(["SPY", "QQQ"], "1d", "2020-01-01", "2021-01-01")
    assert len(al.calls) == n1                                  # fully cached: zero requests
    dl.sync(["SPY"], "1d", "2020-01-01", "2021-06-01")          # extension: only the new tail is requested
    last = al.calls[-1]
    assert last[0] == ("SPY",) and last[2] >= T("2021-01-01")
    df = cache.read("alpaca", "sip", "1d", "SPY")
    assert df.index.is_unique and df.index.is_monotonic_increasing


def test_empty_ranges_are_remembered_too(tmp_path):
    class EmptyAlpaca(FakeAlpaca):
        def stock_bars(self, symbols, tf, a, b):
            self.calls.append(1)
            return {s: fake_bars(a, a) for s in symbols}        # provider returns nothing
    al, cache = EmptyAlpaca(), BarCache(tmp_path)
    dl = Downloader(al, cache, log=lambda s: None)
    dl.sync(["NEWCO"], "1d", "2020-01-01", "2020-03-01")
    dl.sync(["NEWCO"], "1d", "2020-01-01", "2020-03-01")
    assert len(al.calls) == 1


def test_never_caches_today(tmp_path):
    cache, al = BarCache(tmp_path), FakeAlpaca()
    Downloader(al, cache, log=lambda s: None).sync(["SPY"], "1d", "2020-01-01", pd.Timestamp.now("UTC") + pd.Timedelta(days=5))
    assert all(c[3] <= safe_end() for c in al.calls)


def test_atomic_write_leaves_no_temp_files(tmp_path):
    cache = BarCache(tmp_path)
    cache.write("alpaca", "sip", "1d", "SPY", fake_bars("2020-01-01", "2020-02-01"), (T("2020-01-01"), T("2020-02-01")))
    leftovers = [p.name for p in tmp_path.rglob("*") if ".tmp" in p.name]
    assert leftovers == []
    meta = json.loads(cache._meta_path(cache.path("alpaca", "sip", "1d", "SPY")).read_text())
    assert meta["rows"] > 0 and len(meta["sha256"]) == 64


# ------------------------------------------------------------------ corporate actions
def raw_daily():
    idx = pd.DatetimeIndex(pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]).tz_localize("America/New_York").tz_convert("UTC"))
    # 4-for-1 split effective (ex-date) 2020-01-06: raw prices drop from 400 to 100
    c = np.array([400.0, 404.0, 101.0, 102.0, 103.0])
    return pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": [1000.0, 1000, 4000, 4000, 4000]}, index=idx)


def test_split_adjustment_removes_the_discontinuity_and_scales_volume():
    acts = pd.DataFrame([("X", "2020-01-06", "split", 4.0, 0.0)], columns=["symbol", "ex_date", "kind", "ratio", "rate"])
    acts["ex_date"] = pd.to_datetime(acts["ex_date"])
    adj = adjust_bars(raw_daily(), acts)
    assert adj.close.tolist() == pytest.approx([100.0, 101.0, 101.0, 102.0, 103.0])
    assert adj.volume.tolist() == pytest.approx([4000.0] * 5)
    assert adj.raw_close.iloc[0] == 400.0
    assert check_bars(adj, "X", "1d", crypto=False).ok


def test_total_return_adjustment_uses_prior_raw_close_hand_computed():
    acts = pd.DataFrame([("X", "2020-01-07", "dividend", 1.0, 2.04)], columns=["symbol", "ex_date", "kind", "ratio", "rate"])
    acts["ex_date"] = pd.to_datetime(acts["ex_date"])
    adj = adjust_bars(raw_daily(), acts, total_return=True)
    f = 1 - 2.04 / 101.0                                         # previous raw close before 2020-01-07 is 101
    assert adj.close.iloc[:3].tolist() == pytest.approx((raw_daily().close.iloc[:3] * f).tolist())
    assert adj.close.iloc[3:].tolist() == pytest.approx([102.0, 103.0])
    plain = adjust_bars(raw_daily(), acts, total_return=False)
    assert plain.close.tolist() == raw_daily().close.tolist()    # dividends ignored unless total_return


def test_split_and_dividend_compose():
    acts = pd.DataFrame([("X", "2020-01-06", "split", 4.0, 0.0), ("X", "2020-01-08", "dividend", 1.0, 1.0)], columns=["symbol", "ex_date", "kind", "ratio", "rate"])
    acts["ex_date"] = pd.to_datetime(acts["ex_date"])
    adj = adjust_bars(raw_daily(), acts, total_return=True)
    f = 1 - 1.0 / 102.0
    assert adj.close.tolist() == pytest.approx([100 * f, 101 * f, 101 * f, 102 * f, 103.0])


# ------------------------------------------------------------------ session handling (uses the real NYSE calendar)
def intraday_15m(day, close_hour=16):
    """Pre-market, regular and after-hours 15m bars for one session (ET)."""
    idx = pd.date_range(f"{day} 04:00", f"{day} 19:45", freq="15min", tz="America/New_York").tz_convert("UTC")
    return pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0}, index=pd.DatetimeIndex(idx, name="ts"))


def test_rth_filter_keeps_only_regular_session_including_half_days():
    full = rth_filter(intraday_15m("2024-03-04"))               # normal Monday: 09:30-16:00 = 26 bars
    assert len(full) == 26 and full.index[0] == pd.Timestamp("2024-03-04 14:30", tz="UTC")
    half = rth_filter(intraday_15m("2024-07-03"))               # early close 13:00 ET = 14 bars
    assert len(half) == 14
    assert len(rth_filter(intraday_15m("2024-03-02"))) == 0     # Saturday: nothing


def test_hourly_bars_are_anchored_at_the_open_not_the_clock():
    h = resample_rth(rth_filter(intraday_15m("2024-03-04")), 60)
    # 09:30-10:30, ..., 14:30-15:30, and a final 30-minute bar 15:30-16:00
    assert len(h) == 7 and h.index[0] == pd.Timestamp("2024-03-04 14:30", tz="UTC")
    assert h.volume.iloc[0] == 4000.0 and h.volume.iloc[-1] == 2000.0


# ------------------------------------------------------------------ quality checks catch planted defects
def clean_daily(n=300):
    rng = np.random.default_rng(0)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    idx = pd.bdate_range("2021-01-04", periods=n).tz_localize("America/New_York").tz_convert("UTC")
    return pd.DataFrame({"open": c, "high": c * 1.005, "low": c * 0.995, "close": c, "volume": 1e6}, index=pd.DatetimeIndex(idx, name="ts"))


def checks(rep):
    return {i.check: i.severity for i in rep.issues}


def test_quality_clean_data_has_no_fail():
    df = clean_daily()
    df = df[~df.index.tz_convert("America/New_York").tz_localize(None).normalize().isin(pd.to_datetime(["2021-01-18", "2021-02-15", "2021-04-02", "2021-05-31", "2021-07-05", "2021-09-06", "2021-11-25", "2021-12-24"]))]
    assert check_bars(df, "T", "1d").ok


def test_quality_detects_planted_defects():
    df = clean_daily()
    bad = df.copy()
    bad.iloc[50, bad.columns.get_loc("high")] = bad.iloc[50]["low"] - 1          # high < low
    assert checks(check_bars(bad, "T", "1d"))["ohlc_inconsistent"] == "FAIL"
    dup = pd.concat([df, df.iloc[[10]]]).sort_index()
    assert checks(check_bars(dup, "T", "1d"))["duplicate_timestamps"] == "FAIL"
    spike = df.copy()
    spike.iloc[100, spike.columns.get_loc("close")] *= 1.5                        # one-bar spike that reverses
    for c in ("open", "high", "low"):
        spike.iloc[100, spike.columns.get_loc(c)] = spike.iloc[100]["close"]
    spike.iloc[100, spike.columns.get_loc("high")] *= 1.001
    assert "possible_bad_ticks" in checks(check_bars(spike, "T", "1d"))
    gap = df.drop(df.index[150:160])
    assert checks(check_bars(gap, "T", "1d"))["missing_sessions"] in ("WARN", "FAIL")
    unadj = df.copy()
    unadj.iloc[200:, :4] = unadj.iloc[200:, :4] * 0.25                            # an unadjusted 4:1 split
    assert "unexplained_large_moves" in checks(check_bars(unadj, "T", "1d"))


def test_cross_check_flags_disagreeing_sources():
    a = clean_daily()
    b = a.copy()
    assert cross_check(a, b)["ok"]
    b.iloc[::10, b.columns.get_loc("close")] *= 1.01                              # 100 bps disagreement on 10% of bars
    assert not cross_check(a, b)["ok"]


# ------------------------------------------------------------------ universe parsing
def test_universe_parsers_handle_symbol_formats():
    rows = "".join(f"<tr><td>{s}</td><td>Name {s}</td></tr>" for s in [f"A{i:03d}"[:4] for i in range(420)] + ["BRK.B", "BF.B"])
    html = f"<table><tr><th>Symbol</th><th>Security</th></tr>{rows}</table>"
    out = parse_sp500(html)
    assert "BRK.B" in out and len(out) == len(set(out))
    html2 = "<table><tr><th>Ticker</th><th>Company</th></tr>" + "".join(f"<tr><td>T{i:02d}</td><td>c</td></tr>" for i in range(100)) + "</table>"
    assert len(parse_ndx(html2)) == 100
    with pytest.raises(ValueError):
        parse_ndx("<table><tr><th>Year</th></tr><tr><td>2020</td></tr></table>")

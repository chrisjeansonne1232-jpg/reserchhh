import numpy as np
import pandas as pd
import pytest

from edgelab.data import holdout as H
from edgelab.data.cache import BarCache
from edgelab.registry import Registry

T = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731


@pytest.fixture
def env(tmp_path, monkeypatch):
    idx = pd.bdate_range("2016-01-04", "2026-01-02", tz="UTC")
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1e6, "trade_count": 1.0, "vwap": 100.0}, index=pd.DatetimeIndex(idx, name="ts"))
    cache = BarCache(tmp_path / "cache")
    cache.write("alpaca", "sip", "1d", "SPY", df, (idx[0], idx[-1] + pd.Timedelta(days=1)))
    cache.write("alpaca", "crypto", "1d", "BTC/USD", df.loc["2021-01-01":], (T("2021-01-01"), idx[-1] + pd.Timedelta(days=1)))
    monkeypatch.setattr("edgelab.data.loader.BarCache", lambda: cache)
    reg = Registry(tmp_path / "lab.sqlite")
    return {"idx": idx, "path": tmp_path / "holdout.json", "reg": reg, "cache": cache}


def test_freeze_is_20_percent_and_one_time(env):
    m = H.freeze_holdout(env["idx"], 0.2, env["path"], env["reg"])
    frac_after = (env["idx"] >= pd.Timestamp(m["holdout_start_utc"])).mean()
    assert 0.19 < frac_after < 0.21
    with pytest.raises(H.HoldoutError):
        H.freeze_holdout(env["idx"], 0.1, env["path"], env["reg"])
    assert env["reg"].events("VAULT_SEAL") and env["reg"].verify_chain()


def test_research_loader_never_returns_holdout_bars_even_if_asked(env):
    H.freeze_holdout(env["idx"], 0.2, env["path"], env["reg"])
    cut = H.holdout_start(env["path"])
    for end in (None, "2026-01-01", "2030-01-01", cut + pd.Timedelta(days=400)):
        df = H.load_research_bars("SPY", "1d", end=end, path=env["path"], adjust="raw")
        assert df.index[-1] < cut
    # the same single cut-off applies to every asset, including crypto that starts later
    assert H.load_research_bars("BTC/USD", "1d", path=env["path"]).index[-1] < cut


def test_holdout_opens_once_per_strategy_and_is_logged(env):
    H.freeze_holdout(env["idx"], 0.2, env["path"], env["reg"])
    df, cut = H.open_holdout("SPY", "1d", strategy_id="S1", reason="final test", registry=env["reg"], path=env["path"], adjust="raw")
    assert df.index[-1] >= cut and df.index[0] < cut                # warm-up history + holdout
    with pytest.raises(H.HoldoutError):
        H.open_holdout("SPY", "1d", strategy_id="S1", reason="second look", registry=env["reg"], path=env["path"], adjust="raw")
    H.open_holdout("SPY", "1d", strategy_id="S2", reason="final test", registry=env["reg"], path=env["path"], adjust="raw")
    ev = [e for e in env["reg"].events("FINAL_TEST") if e["payload"]["event"] == "HOLDOUT_OPENED"]
    assert [e["payload"]["strategy_id"] for e in ev] == ["S1", "S2"] and env["reg"].verify_chain()


def test_not_frozen_means_research_loader_refuses(env):
    with pytest.raises(H.HoldoutError):
        H.load_research_bars("SPY", "1d", path=env["path"])

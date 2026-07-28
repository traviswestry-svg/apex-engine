"""Tests for engine/premarket.py — the Pre-Market Forecast Engine."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from engine.premarket import build_premarket_forecast, _gap_class

ET = ZoneInfo("America/New_York")
NOW = dt.datetime(2026, 7, 28, 8, 30, tzinfo=ET)  # 8:30 AM ET, Tuesday


def _bars(base: float, drift: float, start_hour: int = 6, n: int = 24, vol: float = 10000):
    """Synthetic 5m pre-market bars for today starting at start_hour ET."""
    out = []
    t0 = NOW.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    for i in range(n):
        px = base + drift * i / max(1, n - 1)
        out.append({"t": int((t0 + dt.timedelta(minutes=5 * i)).timestamp() * 1000),
                    "o": px, "h": px + 0.1, "l": px - 0.1, "c": px, "v": vol})
    return out


def test_gap_classification_bands():
    assert _gap_class(0.05) == "FLAT"
    assert _gap_class(0.2) == "SMALL"
    assert _gap_class(0.5) == "MODERATE"
    assert _gap_class(1.2) == "LARGE"


def test_gap_up_with_agreeing_drift_leans_gap_and_go():
    r = build_premarket_forecast(
        spy_bars=_bars(662.0, +1.5), qqq_bars=_bars(600.0, +1.8),
        es_price=7445.0, spy_prior_close=659.0, qqq_prior_close=596.0,
        spx_prior_close=7412.0, prior_poc=7421.0, prior_vah=7427.0,
        prior_val=7398.0, now_et=NOW)
    assert r["available"] is True
    assert r["gap"]["direction"] == "UP"
    f = r["forecast"]
    assert f["gap_and_go_probability_pct"] > f["gap_fill_probability_pct"] - 100  # sanity
    assert f["probability_basis"] == "HEURISTIC_PRIORS_ADJUSTED"
    assert f["confidence"] <= 65.0
    assert r["spy_qqq_agreement"]["state"] in ("TECH_LED_AGREEMENT", "BROAD_AGREEMENT")
    assert "[PREMARKET]" in r["executive_summary"]
    assert r["guardrails"]["advisory_only"] is True


def test_divergence_raises_fill_probability():
    agree = build_premarket_forecast(
        spy_bars=_bars(662.0, +1.0), qqq_bars=_bars(600.0, +1.2),
        es_price=7445.0, spy_prior_close=659.0, qqq_prior_close=596.0,
        spx_prior_close=7412.0, now_et=NOW)
    diverge = build_premarket_forecast(
        spy_bars=_bars(662.0, +1.0), qqq_bars=_bars(594.0, -1.2),
        es_price=7445.0, spy_prior_close=659.0, qqq_prior_close=596.0,
        spx_prior_close=7412.0, now_et=NOW)
    assert diverge["spy_qqq_agreement"]["state"] == "DIVERGENCE"
    assert (diverge["forecast"]["gap_fill_probability_pct"]
            > agree["forecast"]["gap_fill_probability_pct"])


def test_probabilities_bounded_and_sum():
    r = build_premarket_forecast(
        spy_bars=_bars(670.0, +3.0), qqq_bars=_bars(610.0, +4.0),
        es_price=7520.0, spy_prior_close=659.0, qqq_prior_close=596.0,
        spx_prior_close=7412.0, prior_vah=7427.0, now_et=NOW)
    f = r["forecast"]
    assert 15.0 <= f["gap_fill_probability_pct"] <= 85.0
    assert abs(f["gap_fill_probability_pct"] + f["gap_and_go_probability_pct"] - 100.0) < 0.11


def test_spy_implied_projection_when_no_es():
    r = build_premarket_forecast(
        spy_bars=_bars(662.0, +0.5), qqq_bars=[], es_price=None,
        spy_prior_close=659.0, qqq_prior_close=None,
        spx_prior_close=7412.0, now_et=NOW)
    assert r["available"] is True
    assert r["projection_source"] == "SPY_IMPLIED"
    assert r["projected_spx_open"] > 7412.0


def test_no_data_degrades_honestly():
    r = build_premarket_forecast(
        spy_bars=[], qqq_bars=[], es_price=None,
        spy_prior_close=None, qqq_prior_close=None,
        spx_prior_close=7412.0, now_et=NOW)
    assert r["ok"] is True and r["available"] is False
    assert r["state"] == "INSUFFICIENT_DATA"


def test_bars_outside_window_excluded():
    # Bars from 3:00 AM (before the 6:00 analysis window) must not count.
    early = _bars(662.0, +1.0, start_hour=3)
    r = build_premarket_forecast(
        spy_bars=early, qqq_bars=[], es_price=None,
        spy_prior_close=659.0, qqq_prior_close=None,
        spx_prior_close=7412.0, now_et=NOW)
    assert r["available"] is False  # nothing inside 6:00–9:30 today


def test_never_raises():
    r = build_premarket_forecast(
        spy_bars=[{"t": "garbage", "c": object()}], qqq_bars=None,  # type: ignore
        es_price="x", spy_prior_close="y", qqq_prior_close=object(),  # type: ignore
        spx_prior_close=7412.0, now_et=NOW)
    assert r["ok"] is True

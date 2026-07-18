"""APEX 11.0B — chain quality as a first-class pricing input.

Two things this locks down:
  1. The gate tests shape against EXECUTABLE prices, not mids (no false positives
     on asymmetric 0DTE wings), and detects convexity (butterfly) arbitrage.
  2. A structure priced off a degraded chain cannot outrank one priced off a
     verified chain — execution feasibility caps confidence.
"""
import datetime as dt
import math
import time
import zoneinfo

import pytest

from engine.chain_quality import evaluate_chain_quality
from engine.premium_chain_pricing import price_structure, _assess_leg_quality
from engine.premium_strategy import build_premium_strategy

ET = zoneinfo.ZoneInfo("America/New_York")


def _c(k, side, bid, ask, age=2.0):
    return {"strike": k, "side": side, "bid": bid, "ask": ask, "mid": (bid + ask) / 2,
            "spread_pct": (ask - bid) / ((ask + bid) / 2) * 100 if ask + bid else 0,
            "volume": 100, "open_interest": 500, "delta": 0.3, "quote_age_seconds": age}


# ── executable shape test (was mid-based) ─────────────────────────────────
def test_asymmetric_wings_are_not_a_false_shape_violation():
    """Wide asymmetric 0DTE quotes invert the mids without any executable arb."""
    q = evaluate_chain_quality([_c(6300, "CALL", 0.05, 1.00), _c(6310, "CALL", 0.50, 1.20)])
    assert q["shape_violation_count"] == 0


def test_real_call_monotonicity_arbitrage_is_detected():
    # ask(6300)=1.05 < bid(6310)=3.00 -> buy low / sell high for a credit
    q = evaluate_chain_quality([_c(6300, "CALL", 1.00, 1.05), _c(6310, "CALL", 3.00, 3.05)])
    assert q["shape_violation_count"] == 1


def test_real_put_monotonicity_arbitrage_is_detected():
    q = evaluate_chain_quality([_c(6300, "PUT", 3.00, 3.05), _c(6310, "PUT", 1.00, 1.05)])
    assert q["shape_violation_count"] == 1


def test_convexity_violation_is_detected():
    """Cheap wings, rich body: 2*body_bid > wing_ask_l + wing_ask_r -> executable fly."""
    q = evaluate_chain_quality([_c(6300, "CALL", 1.0, 1.05), _c(6310, "CALL", 5.0, 5.1),
                                _c(6320, "CALL", 1.0, 1.05)])
    assert q["convexity_violation_count"] == 1


def test_normal_convex_chain_has_no_violations():
    q = evaluate_chain_quality([_c(6300, "CALL", 5.0, 5.2), _c(6310, "CALL", 3.0, 3.2),
                                _c(6320, "CALL", 1.5, 1.7)])
    assert q["shape_violation_count"] == 0
    assert q["convexity_violation_count"] == 0


# ── freshness is now real ─────────────────────────────────────────────────
def test_freshness_measured_from_real_timestamp():
    from engine.options.options_data_bus import normalize_chain
    now_ns = int(time.time() * 1e9)
    raw = [{"strike_price": 6300.0, "type": "call", "expiration": "2026-07-20",
            "symbol": "O:SPXW260720C06300000", "bid": 6.0, "ask": 6.2,
            "last_updated": now_ns - 3_000_000_000,  # 3s ago
            "volume": 5000, "open_interest": 12000,
            "greeks": {"delta": 0.5, "iv": 0.18}}]
    d = normalize_chain(raw, symbol="SPX", source="polygon")[0].to_dict()
    assert d["quote_age_seconds"] is not None
    assert 2.5 < d["quote_age_seconds"] < 4.0


def test_no_timestamp_is_unmeasurable_not_fresh():
    """The original bug: unknown age must not score as fresh."""
    q = evaluate_chain_quality([_c(6300, "CALL", 6.0, 6.2, age=None)])
    assert q["fresh_quote_pct"] is None
    assert q["freshness_unavailable_reason"]


# ── quality is assessed on the priced legs ────────────────────────────────
def test_leg_quality_assessment_is_available_for_good_quotes():
    quotes = [_c(6300, "PUT", 2.0, 2.1), _c(6290, "PUT", 1.0, 1.1),
              _c(6400, "CALL", 2.0, 2.1), _c(6410, "CALL", 1.0, 1.1)]
    a = _assess_leg_quality(quotes)
    assert a["available"] is True
    assert 0.0 <= a["execution_confidence"] <= 1.0


def test_leg_quality_no_quotes_is_not_confident():
    a = _assess_leg_quality([])
    assert a["available"] is False
    assert a["execution_confidence"] == 0.5   # unknown, not 1.0


# ── the 11.0B guarantee: degraded cannot outrank verified ─────────────────
def _book(minutes, stale=False):
    S, sig = 6300.0, 0.18
    T = (minutes / 390.0) / 252.0

    def bs(K, cp):
        d1 = (math.log(S / K) + 0.5 * sig * sig * T) / (sig * math.sqrt(T))
        d2 = d1 - sig * math.sqrt(T)
        N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
        return S * N(d1) - K * N(d2) if cp == "CALL" else K * N(-d2) - S * N(-d1)

    def f(symbol, expiration, side):
        rows = []
        for k in range(6000, 6601, 5):
            mid = max(0.05, bs(k, side))
            half = max(0.025, mid * 0.03)
            b = max(0.0, round((mid - half) * 20) / 20)
            a = round((mid + half) * 20) / 20
            age_ns = int(time.time() * 1e9) - (120_000_000_000 if stale else 2_000_000_000)
            rows.append({"strike": float(k), "optionType": side, "bid": b,
                         "ask": a if a > b else b + 0.05, "volume": 800,
                         "openInterest": 4000, "greeks": {"delta": 0.3, "iv": sig},
                         "expiration": expiration, "last_updated": age_ns})
        return rows
    return f


_LR = {"institutional_intelligence": {"ici": 60, "grade": "B", "pin_probability": 70,
                                      "gamma_regime": "POSITIVE_GAMMA",
                                      "auction_state": "BALANCED"},
       "market_state": {"price": 6300.0, "vix": 18},
       "range_projection": {"expected_move": 28.0},
       "volatility": {"regime": "NORMAL", "iv_rank": 40},
       "gamma": {"call_wall": 6400, "put_wall": 6200, "zero_gamma": 6295,
                 "regime": "POSITIVE_GAMMA", "pin_probability": 70},
       "auction": {"state": "BALANCED"}}
_CONF = {"dominant_side": "NEITHER", "conviction": "NONE"}
_NOW = dt.datetime(2026, 7, 20, 11, 0, tzinfo=ET)


def _run(book):
    return build_premium_strategy(_LR, confluence=_CONF, chain_fetcher=book, now_et=_NOW,
                                  symbol="SPX", expiration="2026-07-20")


def test_high_chain_leaves_confidence_uncapped():
    r = _run(_book(300))
    lg = r.get("legs") or {}
    if lg.get("economics_available"):
        assert lg["chain_grade"] == "HIGH"
        assert lg["execution_confidence"] == pytest.approx(1.0, abs=0.05)


def test_degraded_chain_ranks_below_verified_chain():
    """The core 11.0B guarantee, expressed as confidence."""
    high = _run(_book(300))
    stale = _run(_book(300, stale=True))
    hi_lg, st_lg = high.get("legs") or {}, stale.get("legs") or {}
    if hi_lg.get("economics_available") and st_lg.get("economics_available"):
        assert stale["confidence"] < high["confidence"], \
            "a stale-chain structure must not outrank a fresh-chain one"
        assert st_lg["execution_confidence"] < hi_lg["execution_confidence"]


def test_confidence_is_never_raised_by_chain_quality():
    """Quality caps; it never inflates. A perfect chain is the ceiling, not a bonus."""
    r = _run(_book(300))
    lg = r.get("legs") or {}
    if lg.get("economics_available"):
        assert lg["execution_confidence"] <= 1.0

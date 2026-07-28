"""Tests for engine/component_liveness.py — frozen vs stable detection."""
from __future__ import annotations

from engine.component_liveness import observe, reset, _FROZEN_STREAK


def _payload(trend_score, flow_score, vix, **extra):
    p = {
        "trend": {"trend_score": trend_score, "updated_at": "2026-07-28T16:00:00Z"},
        "flow_intelligence": {"flow_score": flow_score, "updated_at_et": "12:00 ET"},
        "volatility": {"vix": vix},
        "market_regime": {"regime": "NEUTRAL"},
        "consensus": {"recommendation": "NO_TRADE"},
    }
    p.update(extra)
    return p


def setup_function(_):
    reset()


def test_first_observation_all_live():
    r = observe(_payload(42, 70, 18.0), is_rth=True)
    assert r["available"] is True
    assert r["counts"]["LIVE"] >= 1
    assert r["state"] in ("HEALTHY", "QUIET_MARKET_OPEN")


def test_genuinely_stable_market_not_flagged_frozen():
    # Same payload repeated many times, nothing else moving -> QUIET, not FROZEN.
    for _ in range(_FROZEN_STREAK + 3):
        r = observe(_payload(42, 70, 18.0), is_rth=True)
    assert not r["frozen_components"]
    assert r["state"] in ("QUIET_MARKET_OPEN", "HEALTHY")


def test_frozen_component_detected_when_others_move():
    # trend never changes; everything else moves every compose. After the
    # streak threshold, trend should be flagged FROZEN.
    for i in range(_FROZEN_STREAK + 2):
        r = observe(_payload(42, 70 + i, 18.0 + i * 0.1,
                             market_state={"price": 7400 + i},
                             auction={"poc": 7390 + i},
                             dealer_positioning={"gex_score": 50 + i}),
                    is_rth=True)
    assert "trend" in r["frozen_components"]
    assert r["state"] == "FROZEN_COMPONENTS"
    tr = next(c for c in r["components"] if c["component"] == "trend")
    assert tr["status"] == "FROZEN"


def test_market_closed_never_frozen():
    for _ in range(_FROZEN_STREAK + 3):
        r = observe(_payload(42, 70, 18.0), is_rth=False)
    assert not r["frozen_components"]
    assert r["state"] == "QUIET_MARKET_CLOSED"


def test_unavailable_component_flagged():
    r = observe(_payload(42, 70, 18.0,
                         dealer_positioning={"available": False, "state": "ERROR"}),
                is_rth=True)
    assert "dealer_positioning" in r["unavailable_components"]


def test_timestamp_only_change_still_counts_as_unchanged():
    # A component that ONLY updates its clock (classic frozen-feed signature)
    # must be treated as unchanged.
    for i in range(_FROZEN_STREAK + 2):
        r = observe(_payload(42, 70 + i, 18.0 + i * 0.1,
                             market_state={"price": 7400 + i},
                             auction={"poc": 7390 + i},
                             # trend only bumps its timestamp, not its value:
                             ),
                    is_rth=True)
    tr = next(c for c in r["components"] if c["component"] == "trend")
    # trend value (score 42) never changed despite ts churn in other calls
    assert tr["unchanged_composes"] >= _FROZEN_STREAK


def test_never_raises_on_garbage():
    r = observe({"trend": object(), "flow_intelligence": [1, 2, object()]}, is_rth=True)  # type: ignore
    assert r["ok"] is True

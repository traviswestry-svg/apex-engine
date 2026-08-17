"""Range Intelligence — canonical Morning Brief context corrections.

Locks in the six required corrections: one authoritative spot/expected-move,
levels separated by purpose, envelope-constrained zone selection, pre-open
range-used disabled, degraded gating, and the four presentation sections.
"""
from engine.range_intelligence import build_range_intelligence


def _bus():
    return {
        "market_state": {
            "price": 7790.0, "gamma_regime": "POSITIVE_GAMMA", "auction_state": "BALANCED",
            "vah": 7800.0, "val": 7760.0, "poc": 7780.0, "vwap": 7790.0,
            "call_wall": 8000.0, "put_wall": 7700.0, "zero_gamma": 7799.0, "flow_bias": "NEUTRAL",
        },
        "structure": {"prev_day_high": 7816.70, "prev_day_low": 7737.95, "prev_close": 7798.50},
        "overnight_game_plan": {"es_price": 7802.0, "overnight_high": 7804.24,
                                "overnight_low": 7770.0, "prior_close": 7798.50},
        "volatility": {"vix": 13.0, "regime": "LOW"},
        "strike_magnets": {"magnets": [
            {"type": "GAMMA_NODE", "side": "ABOVE", "strike": 7799.0},
            {"type": "PUT_WALL", "side": "BELOW", "strike": 7700.0},
        ]},
        "dealer_positioning": {"gamma_regime": "POSITIVE_GAMMA"},
    }


CANON = {"spot": 7798.99, "em_low": 7771.62, "em_high": 7826.36}


def _ri(**kw):
    return build_range_intelligence(_bus(), market_open=kw.pop("market_open", False),
                                    ticker="SPX", **kw)["range_intelligence"]


def test_uses_canonical_spot_and_expected_move_not_vix():
    ri = _ri(canonical=CANON)
    assert ri["canonical"]["spot"] == 7798.99
    assert ri["canonical"]["used"] is True
    assert ri["expected_session_range"]["low"] == 7771.62
    assert ri["expected_session_range"]["high"] == 7826.36
    assert ri["expected_session_range"]["source"] == "MORNING_BRIEF_CANONICAL"
    assert "EXPECTED_MOVE_DERIVED_FROM_VIX" not in ri["quality_flags"]


def test_falls_back_to_vix_only_without_canonical():
    ri = _ri()  # no canonical
    assert ri["canonical"]["used"] is False
    assert ri["expected_session_range"]["source"] == "VIX_DERIVED_FALLBACK"
    assert "EXPECTED_MOVE_DERIVED_FROM_VIX" in ri["quality_flags"]


def test_put_wall_is_tail_risk_not_the_low_zone():
    ri = _ri(canonical=CANON)
    # The 7700 put wall must NOT become the projected low zone.
    assert ri["projected_low_zone"]["low"] > 7760
    tail_prices = [t["price"] for t in ri["tail_risk_levels"]]
    assert 7700.0 in tail_prices
    assert all(t["classification"] in ("TAIL_RISK_LEVEL", "SECONDARY_SUPPORT")
               for t in ri["tail_risk_levels"])
    # 71pts beyond the envelope must never sit inside the normal range.
    assert 7700.0 not in (ri["projected_low_zone"]["low"], ri["projected_low_zone"]["high"])


def test_far_outlier_excluded_but_near_outlier_allowed_classification():
    ri = _ri(canonical=CANON)
    classes = {t["classification"] for t in ri["tail_risk_levels"]}
    # Structural walls beyond the envelope are TAIL_RISK; a value level just
    # outside is SECONDARY_SUPPORT — both excluded from the normal range.
    assert "TAIL_RISK_LEVEL" in classes


def test_call_wall_is_expansion_target():
    ri = _ri(canonical=CANON)
    exp = {t["label"]: t["classification"] for t in ri["expansion_targets"]}
    assert exp.get("Call wall") == "EXPANSION_TARGET"


def test_previous_day_high_is_intermediate_target():
    ri = _ri(canonical=CANON)
    prices = [t["price"] for t in ri["intermediate_targets"]]
    assert 7816.7 in prices


def test_pre_open_range_used_and_exhaustion_disabled():
    ri = _ri(canonical=CANON, market_open=False)
    assert ri["range_used_percent"] is None
    assert ri["range_used_evaluated"] is False
    assert ri["range_exhaustion_risk"] == "NOT_EVALUATED"
    assert ri["range_used_method"] in ("WAITING_FOR_RTH", "WITHHELD_DEGRADED")


def test_remaining_measured_from_envelope():
    ri = _ri(canonical=CANON)
    # spot 7798.99, envelope 7771.62..7826.36
    assert abs(ri["upside_remaining_points"] - (7826.36 - 7798.99)) < 0.01
    assert abs(ri["downside_remaining_points"] - (7798.99 - 7771.62)) < 0.01


def test_range_used_computed_only_with_real_rth_session():
    bus = _bus()
    bus["structure"]["session_high"] = 7810.0
    bus["structure"]["session_low"] = 7785.0
    ri = build_range_intelligence(bus, market_open=True, ticker="SPX", canonical=CANON)["range_intelligence"]
    assert ri["range_used_evaluated"] is True
    assert ri["range_used_percent"] is not None
    assert ri["range_used_method"] == "SESSION_RANGE"


def test_degraded_runtime_withholds_conclusions():
    ri = _ri(canonical=CANON, runtime={"state": "DEGRADED", "degraded": True, "data_fresh": False})
    assert ri["range_used_percent"] is None
    assert ri["range_exhaustion_risk"] == "NOT_EVALUATED"
    assert "live_scanner" in ri["stale_inputs"]
    assert ri["runtime_state"] in ("DEGRADED", "DEGRADED_PREOPEN")
    # canonical projection is still preserved (not blanked)
    assert ri["expected_session_range"]["low"] == 7771.62


def test_four_presentation_sections_present():
    ri = _ri(canonical=CANON)
    for key in ("expected_session_range", "immediate_reaction_zones",
                "expansion_targets", "tail_risk_levels"):
        assert key in ri

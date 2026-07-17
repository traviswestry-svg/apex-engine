from engine.confidence_attribution import build_confidence_attribution


def _ici():
    return {
        "ici": 70.0,
        "components": {"conviction": 80, "freshness": 50, "gamma_stability": 80, "flow_momentum": 60},
        "weights": {"conviction": .5, "freshness": .2, "gamma": .15, "momentum": .15},
    }


def _engines():
    return [
        {"engine": "trend", "label": "Trend", "vote": "BULLISH", "contribution": .12, "data_available": True, "health_status": "OK", "weight": .15, "strength": .8},
        {"engine": "gamma", "label": "Gamma", "vote": "BEARISH", "contribution": .04, "data_available": True, "health_status": "OK", "weight": .08, "strength": .5},
        {"engine": "execution", "label": "Execution", "vote": "NEUTRAL", "contribution": 0, "data_available": False, "health_status": "NO_SIGNAL", "weight": .2, "strength": 0},
    ]


def test_attribution_reconstructs_weighted_components():
    out = build_confidence_attribution(ici=_ici(), engine_contributions=_engines(), consensus={"consensus_direction": "BULLISH"})
    assert out["reconstructed_base_score"] == 71.0
    assert out["effective_confidence"] == 71.0
    assert out["methodology"]["reliability_is_additive"] is False


def test_chain_quality_only_multiplies_gamma_component():
    quality = {"score": 50, "score_confidence_pct": 100, "gate_passed": False}
    out = build_confidence_attribution(ici=_ici(), engine_contributions=_engines(), chain_quality=quality)
    rows = {x["key"]: x for x in out["components"]}
    assert rows["conviction"]["adjusted_points"] == rows["conviction"]["base_points"]
    assert rows["gamma_stability"]["adjusted_points"] < rows["gamma_stability"]["base_points"]
    assert any(x["type"] == "CHAIN_QUALITY" for x in out["adjustments"])


def test_flow_authenticity_only_multiplies_flow_component():
    out = build_confidence_attribution(
        ici=_ici(), engine_contributions=_engines(),
        flow_authenticity={"state": "SCHEDULED_AUTOMATED_FLOW_PENDING_CONFIRMATION", "directional_confidence_multiplier": .45},
    )
    rows = {x["key"]: x for x in out["components"]}
    assert rows["flow_momentum"]["adjusted_points"] == round(rows["flow_momentum"]["base_points"] * .45, 2)
    assert rows["gamma_stability"]["adjusted_points"] == rows["gamma_stability"]["base_points"]


def test_event_regime_is_final_multiplier_not_additive_points():
    out = build_confidence_attribution(
        ici=_ici(), engine_contributions=_engines(),
        event_regime={"state": "EVENT_IMPULSE", "alert_confidence_multiplier": .35},
    )
    assert out["effective_confidence"] == round(71.0 * .35, 1)
    evt = next(x for x in out["adjustments"] if x["type"] == "EVENT_REGIME")
    assert evt["multiplier"] == .35
    assert evt["point_effect"] < 0


def test_directional_contributions_are_signed():
    out = build_confidence_attribution(ici=_ici(), engine_contributions=_engines())
    rows = {x["engine"]: x for x in out["engine_directional_contributions"]}
    assert rows["trend"]["signed_contribution"] > 0
    assert rows["gamma"]["signed_contribution"] < 0
    assert rows["execution"]["signed_contribution"] == 0


def test_pipeline_exposes_attribution_without_replacing_reported_confidence():
    import apex_engines
    bars = [{"c": 5000 + i, "h": 5002 + i, "l": 4998 + i, "v": 1000 + i} for i in range(260)]
    out = apex_engines.build_institutional_decision(
        ticker="SPX",
        flow_snapshot={"gex_score": 50, "stock_price": 5250, "approved_side": "NONE"},
        spy_bars=bars, qqq_bars=bars, daily_bars=bars, intraday_bars=bars[-30:],
        session_is_tradeable=False,
    )
    assert out["confidence_attribution"]["base_score"] == out["confidence"]
    assert out["decision"]["confidence"] == out["confidence"]

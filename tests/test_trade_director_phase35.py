from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def full_intraday_evidence(**overrides):
    x = {
        "gamma_regime": "NEGATIVE",
        "auction_state": "VALUE_EXPANSION",
        "flow_state": "ACCELERATING",
        "volatility_regime": "EXPANDING",
        "trend_persistence": "STRONG",
        "liquidity_state": "NORMAL",
        "structure_score": 88,
        "flow_score": 90,
        "dealer_score": 82,
        "higher_timeframe_score": 76,
        "fundamental_score": 55,
    }
    x.update(overrides)
    return x


def test_router_ranks_multiple_functions_and_is_style_relative():
    from engine.trade_director_trade_function_router import build_trade_function_router
    d = build_trade_function_router(full_intraday_evidence())
    assert len(d["rankings"]) == 6
    assert d["best_fit_function"]["function"] in {"QUICK_SCALP", "SCALP_15M", "SCALP_30M", "INTRADAY"}
    assert d["selected_function"]["style_fit_grade"] in {"A+", "A", "B+", "B", "C", "D"}
    assert d["empirical_status"] == "HEURISTIC_PRIOR_PENDING_CALIBRATION"


def test_balanced_positive_gamma_can_favor_quick_scalp_not_intraday():
    from engine.trade_director_trade_function_router import build_trade_function_router
    d = build_trade_function_router(full_intraday_evidence(
        gamma_regime="POSITIVE", auction_state="BALANCED", flow_state="MIXED",
        volatility_regime="COMPRESSED", trend_persistence="BALANCED",
        structure_score=82, flow_score=55, dealer_score=74, higher_timeframe_score=50,
    ))
    ranks = {x["function"]: x for x in d["rankings"]}
    assert ranks["QUICK_SCALP"]["style_fit_score"] > ranks["INTRADAY"]["style_fit_score"]


def test_missing_evidence_fails_closed_without_fabricated_a_plus():
    from engine.trade_director_trade_function_router import build_trade_function_router
    d = build_trade_function_router({})
    assert d["evidence_coverage_pct"] == 0
    assert all(x["style_fit_grade"] == "INSUFFICIENT_DATA" for x in d["rankings"])


def test_allocation_uses_selected_style_fit_not_global_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_GOVERNANCE_DB", str(tmp_path / "g.db"))
    from engine.trade_director_session_allocation import build_session_allocation, record_confirmed_trade
    for i, qty in enumerate((1, 3)):
        record_confirmed_trade(ticker="SPX", side="CALL", quantity=qty,
                               session_date="2026-07-23", created_at=f"2026-07-23T09:4{i}:00")
    reduced = build_session_allocation(environment_quality="POOR", trade_function="QUICK_SCALP",
                                       style_fit_grade="A", style_fit_score=84, session_date="2026-07-23")
    assert reduced["recommended_contracts"] == 3
    full = build_session_allocation(environment_quality="POOR", trade_function="QUICK_SCALP",
                                    style_fit_grade="A+", style_fit_score=92, session_date="2026-07-23")
    assert full["recommended_contracts"] == 4


def test_assistant_has_router_and_market_directive_remains_first():
    html = (ROOT / "templates" / "assistant.html").read_text()
    assert html.index('id="app"') < html.index('id="sessionAllocation"')
    assert "Trade Function Router & Session Allocation" in html
    assert "Quick Scalp <5m" in html
    assert "SCALP_15M" in html and "LEAP" in html
    assert "never places, modifies, or authorizes an order" in html


def test_phase35_routes_registered():
    app = (ROOT / "app.py").read_text()
    assert '/api/trade-function-router' in app
    assert 'td35_build_trade_function_router' in app
    assert 'style_fit_grade' in app

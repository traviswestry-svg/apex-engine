from datetime import date, timedelta

from engine.gamma import build_gamma_from_quantdata_response
from engine.dynamic_state import build_dynamic_state
from engine.evidence_eligibility import evaluate_evidence_eligibility, summarize_evidence_eligibility
from engine.decision_reasoning_contracts import make_engine_opinion, build_correlation_aware_consensus


def _gamma_payload():
    today = date.today()
    tomorrow = (today + timedelta(days=1)).isoformat()
    next_week = (today + timedelta(days=7)).isoformat()
    today_str = today.isoformat()
    return {"data": {"SPX": {"stockPrice": 6500, "exposureMap": {
        today_str: {"6450": {"callExposure": 10, "putExposure": -2}, "6500": {"callExposure": 12, "putExposure": -2}, "6550": {"callExposure": 9, "putExposure": -1}},
        tomorrow: {"6450": {"callExposure": 5, "putExposure": -1}, "6500": {"callExposure": 6, "putExposure": -1}},
        next_week: {"6450": {"callExposure": 2, "putExposure": -1}, "6500": {"callExposure": 2, "putExposure": -1}},
    }}}}


def test_gamma_maturity_concentration_and_durability_are_exposed():
    g = build_gamma_from_quantdata_response(_gamma_payload(), "SPX")
    m = g["gamma_term_structure"]["maturity_concentration"]
    assert 0 < m["zero_dte_gamma_share"] < 1
    assert m["zero_one_dte_gamma_share"] > m["zero_dte_gamma_share"]
    assert m["structure_durability"] in {"LOW", "MEDIUM", "HIGH"}
    assert g["gamma_path"]["spot"] == 6500.0


def test_gamma_capacity_requires_real_expected_move_and_never_fabricates_it():
    g = build_gamma_from_quantdata_response(_gamma_payload(), "SPX")
    no_em = build_dynamic_state({"gamma": g})
    assert no_em["gamma_context"]["capacity_state"] == "UNAVAILABLE"
    assert no_em["gamma_context"]["capacity_ratio"] is None

    with_em = build_dynamic_state({"gamma": g, "structured": {"expected_move": {"one_sigma": 45.0}}})
    gc = with_em["gamma_context"]
    assert gc["expected_move_points"] == 45.0
    assert gc["capacity_ratio"] is not None
    assert gc["capacity_state"] in {"WEAK", "MODERATE", "STRONG"}


def test_flow_eligibility_marks_redundancy_without_double_discount():
    op = make_engine_opinion(engine_name="flow", raw_direction="BULLISH", reliability=1.0,
                             strength=1.0, independence_factor=0.2)
    ds = {"flow_excitation": {"available": True, "independent_evidence_factor": 0.2}}
    e = evaluate_evidence_eligibility("flow", op, ds)
    assert e["state"] == "DISCOUNTED"
    assert e["weight_factor"] == 1.0
    assert e["discount_delegated_to_existing_factor"] is True
    op["evidence_eligibility"] = e
    op["eligibility_state"] = e["state"]
    op["eligibility_weight_factor"] = e["weight_factor"]
    c = build_correlation_aware_consensus([op])
    assert c["raw_directional_evidence"]["BULLISH"] == 0.2


def test_context_only_and_release_watch_only_do_not_enter_consensus():
    dealer = make_engine_opinion(engine_name="dealer", raw_direction="BULLISH", reliability=1.0, strength=1.0)
    e = evaluate_evidence_eligibility("dealer", dealer, {"gamma_context": {"structure_durability": "LOW"}})
    dealer["evidence_eligibility"] = e; dealer["eligibility_state"] = e["state"]; dealer["eligibility_weight_factor"] = e["weight_factor"]
    assert e["state"] == "CONTEXT_ONLY"
    assert build_correlation_aware_consensus([dealer])["eligible_count"] == 0

    flow = make_engine_opinion(engine_name="flow", raw_direction="BEARISH", reliability=1.0, strength=1.0)
    ew = evaluate_evidence_eligibility("flow", flow, {"event_phase": {"phase": "RELEASE"}})
    assert ew["state"] == "WATCH_ONLY"
    assert ew["consensus_eligible"] is False


def test_eligibility_summary_reports_effective_independent_evidence():
    a = make_engine_opinion(engine_name="flow", raw_direction="BULLISH", reliability=1.0, strength=1.0, independence_factor=0.25)
    a["evidence_eligibility"] = {"state": "DISCOUNTED", "weight_factor": 1.0, "reasons": ["CONTINUING_FLOW_BURST"]}
    b = make_engine_opinion(engine_name="auction", raw_direction="BULLISH", reliability=1.0, strength=1.0)
    b["evidence_eligibility"] = {"state": "FULL", "weight_factor": 1.0, "reasons": []}
    s = summarize_evidence_eligibility([a, b])
    assert s["counts"]["DISCOUNTED"] == 1
    assert s["counts"]["FULL"] == 1
    assert s["effective_independent_evidence"] == 1.25

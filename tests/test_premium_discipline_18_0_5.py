import os
import tempfile

from engine.premium_discipline import (APPROVE, NOT_APPLICABLE, REFUSE,
                                       RefusalLedger,
                                       evaluate_premium_eligibility)


def bus(**overrides):
    lr = {
        "market_state": {"session_state": "RTH", "vix": 18},
        "institutional_intelligence": {
            "auction_state": "BALANCED", "gamma_regime": "POSITIVE_GAMMA",
            "flow_bias": "NEUTRAL", "flow_conviction": 15,
            "flow_contradictions": [], "momentum_probability": 25,
            "pin_probability": 75, "overall_score": 78,
        },
        "range_intelligence": {"range_intelligence": {
            "mean_reversion_probability": 78, "expansion_probability": 22,
            "pin_probability": 75,
        }},
        "volatility": {"vix": 18, "regime": "NORMAL"},
    }
    for k, v in overrides.items():
        lr[k] = v
    return lr


def candidate(**overrides):
    c = {
        "strategy": "IRON_CONDOR", "premium_kind": "CREDIT",
        "tradeable": True, "economics_available": True,
        "confidence": 82, "case": "BALANCED_AUCTION",
        "legs": {"pop": 0.76, "entry_credit": 1.8, "width": 10},
    }
    c.update(overrides)
    return c


def test_clean_contained_market_is_approved():
    d = evaluate_premium_eligibility(bus(), candidate())
    assert d["decision"] == APPROVE
    assert d["eligible"] is True
    assert d["score"] >= d["threshold"]
    assert len(d["factors"]) == 6


def test_unpriceable_candidate_is_refused_even_with_good_market_score():
    d = evaluate_premium_eligibility(bus(), candidate(tradeable=False, economics_available=False,
                                                      case="UNPRICEABLE"))
    assert d["decision"] == REFUSE
    assert any("economics" in b.lower() for b in d["blockers"])


def test_active_turn_is_a_hard_refusal():
    lr = bus()
    lr["institutional_intelligence"]["auction_state"] = "BREAKOUT_PRICE_DISCOVERY"
    lr["institutional_intelligence"]["momentum_probability"] = 80
    d = evaluate_premium_eligibility(lr, candidate())
    assert d["decision"] == REFUSE
    assert any("active directional" in b.lower() for b in d["blockers"])


def test_closed_session_is_refused():
    lr = bus(); lr["market_state"]["session_state"] = "AFTER_HOURS"
    assert evaluate_premium_eligibility(lr, candidate())["decision"] == REFUSE


def test_debit_or_no_trade_is_not_applicable():
    d = evaluate_premium_eligibility(bus(), candidate(strategy="DEBIT_CALL_SPREAD", premium_kind="DEBIT"))
    assert d["decision"] == NOT_APPLICABLE


def test_threshold_is_governed_and_cannot_be_overridden_by_score():
    d = evaluate_premium_eligibility(bus(), candidate(), threshold=99)
    assert d["decision"] == REFUSE
    assert any("threshold" in b.lower() for b in d["blockers"])


def test_refusal_ledger_is_idempotent_and_scores_decisions():
    with tempfile.TemporaryDirectory() as td:
        ledger = RefusalLedger(os.path.join(td, "test.db"))
        d = evaluate_premium_eligibility(bus(), candidate())
        a = ledger.record(session_date="2026-07-19", ticker="SPX", candidate=candidate(), decision=d)
        b = ledger.record(session_date="2026-07-19", ticker="SPX", candidate=candidate(), decision=d)
        assert a["id"] == b["id"]
        assert ledger.scorecard()["total"] == 1
        assert ledger.scorecard()["approved"] == 1


def test_routes_are_registered_and_nonfatal(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "routes.db"))
    import app as apex_app
    client = apex_app.app.test_client()
    for route in ("/api/premium_discipline", "/api/premium_discipline/decisions",
                  "/api/premium_discipline/scorecard"):
        r = client.get(route)
        assert r.status_code == 200
        assert r.get_json()["ok"] is True

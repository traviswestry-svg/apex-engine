import json
import sqlite3

from flask import Flask

from engine.adaptive_refusal_calibration import CalibrationStore, DEFAULT_WEIGHTS
from engine.premium_discipline import RefusalLedger, evaluate_premium_eligibility
from engine.premium_discipline_routes import register_premium_discipline_routes


def _seed(db_path, count=20, protected=14):
    ledger = RefusalLedger(str(db_path))
    for i in range(count):
        factors = [
            {"code": code, "score": 35 + i % 20, "weight": weight, "detail": "test"}
            for code, weight in DEFAULT_WEIGHTS.items()
        ]
        candidate = {"strategy": "BULL_PUT_CREDIT_SPREAD", "case": f"CASE_{i}",
                     "legs": {"short_put": 5000 + i, "long_put": 4995 + i, "credit": 1.0}}
        decision = {"decision": "REFUSE", "score": 60 + i % 5, "threshold": 65,
                    "blockers": ["below threshold"], "warnings": [], "factors": factors}
        rec = ledger.record(session_date="2026-07-01", ticker="SPX", candidate=candidate, decision=decision)
        outcome = "AVOIDED_STOP" if i < protected else "MISSED_WIN"
        ledger.grade(rec["id"], outcome, -100 if i < protected else 100, "seed", {})


def test_insufficient_data_is_inert(tmp_path):
    store = CalibrationStore(str(tmp_path / "a.db"))
    result = store.run(min_sample=20)
    assert result["recommendation"]["status"] == "INSUFFICIENT_DATA"
    assert result["recommendation"]["operational"] is False


def test_recommendation_requires_promotion(tmp_path):
    db = tmp_path / "b.db"
    _seed(db)
    store = CalibrationStore(str(db))
    result = store.run(min_sample=20)
    assert result["recommendation"]["status"] == "RECOMMENDED"
    before = store.active_policy()
    assert before["source"] == "DEFAULT_GOVERNED_POLICY"
    promoted = store.promote(result["run_id"], promoted_by="test")
    assert promoted["promoted"] is True
    after = store.active_policy()
    assert after["source"] == "PROMOTED_CALIBRATION"
    assert abs(sum(after["weights"].values()) - 1.0) < 0.001


def test_promoted_weights_are_used_by_gate():
    lr = {"market_state": {"session_state": "OPEN"},
          "institutional_intelligence": {"auction_state": "BALANCED", "gamma_regime": "POSITIVE",
                                         "pin_probability": 70, "flow_conviction": 20},
          "range_intelligence": {"range_intelligence": {"mean_reversion_probability": 70,
                                                         "expansion_probability": 20}},
          "volatility": {"vix": 19}}
    candidate = {"strategy": "IRON_CONDOR", "premium_kind": "CREDIT", "tradeable": True,
                 "economics_available": True, "confidence": 80, "legs": {"pop": .75}}
    result = evaluate_premium_eligibility(lr, candidate, threshold=60,
                                          weights={"AUCTION": .4, "REGIME": .1, "GAMMA": .1,
                                                   "FLOW": .1, "VOL": .1, "QUALITY": .2})
    assert result["weights"]["AUCTION"] == .4
    assert result["score"] >= 60


def test_calibration_routes(tmp_path):
    app = Flask(__name__)
    register_premium_discipline_routes(app, last_result_provider=lambda: {}, db_path=str(tmp_path / "c.db"))
    routes = {r.rule for r in app.url_map.iter_rules()}
    assert "/api/premium_discipline/calibration" in routes
    assert "/api/premium_discipline/calibration/run" in routes
    assert "/api/premium_discipline/calibration/promote" in routes
    client = app.test_client()
    assert client.get("/api/premium_discipline/calibration").status_code == 200
    body = client.post("/api/premium_discipline/calibration/run", json={"min_sample": 20}).get_json()
    assert body["ok"] is True

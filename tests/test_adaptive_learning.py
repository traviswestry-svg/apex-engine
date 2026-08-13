import json
import sqlite3

from engine.adaptive_learning import DEFAULT_WEIGHTS, evaluate, record_outcome, recalibrate, summary


def _features(bullish=True):
    hi, lo = (75, 25) if bullish else (25, 75)
    return {"liquidity":hi,"order_flow":hi,"delta":hi,"auction":60 if bullish else 40,
            "structure":hi,"momentum":hi,"gamma":55 if bullish else 45,"vwap":60 if bullish else 40}


def test_cold_start_is_shadow_and_advisory(tmp_path):
    db = tmp_path / "a.db"
    r = evaluate({}, db)
    assert r["status"] == "COLD_START"
    assert r["applied_to_live_scoring"] is False
    assert r["guardrails"]["execution_authority"] is False
    assert r["active_weights"] == DEFAULT_WEIGHTS


def test_record_and_summary(tmp_path):
    db = tmp_path / "a.db"
    oid = record_outcome({"direction":"BULLISH","confidence":72,"won":True,"realized_return":1.2,"features":_features(True)}, db)
    assert oid == 1
    s = summary(db)
    assert len(s["recent_outcomes"]) == 1
    assert s["recent_outcomes"][0]["won"] == 1


def test_recalibration_requires_balanced_minimum_sample(tmp_path):
    db = tmp_path / "a.db"
    for i in range(30):
        won = i % 2 == 0
        record_outcome({"direction":"BULLISH","confidence":70 if won else 60,"won":won,
                        "realized_return":1 if won else -1,"features":_features(won)}, db)
    r = recalibrate(db)
    assert r["mode"] == "SHADOW_LEARNING"
    assert r["weights"] == DEFAULT_WEIGHTS
    assert abs(sum(r["proposed_weights"].values()) - 1.0) < 1e-5
    assert r["proposed_weights"]["liquidity"] != DEFAULT_WEIGHTS["liquidity"]


def test_invalid_direction_rejected(tmp_path):
    try:
        record_outcome({"direction":"NEUTRAL","won":True}, tmp_path / "a.db")
    except ValueError as exc:
        assert "BULLISH or BEARISH" in str(exc)
    else:
        raise AssertionError("expected ValueError")

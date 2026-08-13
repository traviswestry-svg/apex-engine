import importlib
import os


def mod(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_EVIDENCE_DB", str(tmp_path / "evidence.db"))
    import engine.trade_director_institutional_evidence as e31
    import engine.trade_director_performance_calibration as e32
    importlib.reload(e31); importlib.reload(e32)
    return e31, e32


def seed(e31, n=12):
    for i in range(n):
        direction = "CALL" if i % 2 == 0 else "PUT"
        confidence = 55 + (i % 5) * 10
        ctx = {"timestamp": f"2026-07-01T{13+i//6:02d}:{(i%6)*5:02d}:00+00:00", "decision_state":"ARMED",
               "direction":direction, "confidence":confidence, "entry_price":6000.0, "stop_price":5995.0 if direction=="CALL" else 6005.0,
               "target_price":6008.0 if direction=="CALL" else 5992.0,
               "engine_attribution":{"dealer":70+i,"flow":{"score":50+i},"price":80-i}}
        d=e31.capture_decision(ctx, force=True)["decision"]
        win=i%3!=0
        if direction=="CALL": close=6008.0 if win else 5995.0; hi=max(6000,close); lo=min(6000,close)
        else: close=5992.0 if win else 6005.0; hi=max(6000,close); lo=min(6000,close)
        e31.grade_decision(d["decision_id"],[{"timestamp":ctx["timestamp"],"open":6000,"high":hi,"low":lo,"close":close}])


def test_empty_center_is_fail_closed(tmp_path, monkeypatch):
    _, e32=mod(tmp_path, monkeypatch)
    c=e32.build_performance_calibration_center()
    assert c["analytics_state"]=="COLLECTING_EVIDENCE"
    assert c["controls"]["automatic_weight_updates"] is False


def test_performance_and_sessions(tmp_path, monkeypatch):
    e31,e32=mod(tmp_path, monkeypatch); seed(e31)
    p=e32.performance_summary()
    assert p["overall"]["scored_count"]==12
    assert p["by_direction"]["CALL"]["count"]==6
    assert p["by_session"]


def test_calibration_is_empirical(tmp_path, monkeypatch):
    e31,e32=mod(tmp_path, monkeypatch); seed(e31)
    c=e32.confidence_reliability()
    assert c["graded_decisions"]==12
    assert c["brier_score"] is not None
    assert sum(b["count"] for b in c["bands"])==12


def test_engine_attribution_is_descriptive(tmp_path, monkeypatch):
    e31,e32=mod(tmp_path, monkeypatch); seed(e31)
    a=e32.engine_attribution()
    assert {x["engine"] for x in a["engines"]}=={"dealer","flow","price"}
    assert a["method"]=="MEDIAN_SPLIT_DESCRIPTIVE_NOT_CAUSAL"


def test_ledger_filters(tmp_path, monkeypatch):
    e31,e32=mod(tmp_path, monkeypatch); seed(e31)
    ledger=e32.decision_ledger(direction="CALL", limit=3)
    assert ledger["count"]==3
    assert all(x["direction"]=="CALL" for x in ledger["items"])


def test_phase32_never_mutates_policy(tmp_path, monkeypatch):
    e31,e32=mod(tmp_path, monkeypatch); seed(e31)
    c=e32.build_performance_calibration_center()
    assert c["controls"]=={"read_only":True,"automatic_weight_updates":False,"threshold_mutation":False,"policy_promotion":False,"broker_access":False}

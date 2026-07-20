"""Tests for APEX 24.2 Institutional Replay & Simulator."""
from engine import institutional_replay_v242 as replay
from engine import institutional_governance as gov


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(gov, "DB_PATH", str(tmp_path / "gov.db"))


def test_status_is_read_only_and_advisory(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    s = replay.status()
    assert s["status"] == "READY"
    assert s["read_only"] is True
    assert s["immutable_history"] is True
    assert s["simulator_writes_history"] is False
    assert s["broker_order_submission_enabled"] is False


def test_capture_builds_multi_engine_environment(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    out = replay.capture({"ticker": "SPX"}, session_key="S1")
    assert out["created"] is True
    sess = replay.session(out["session_id"])
    env = sess["environment"]
    for engine in ("trading_brain", "regime_intelligence", "forecast_engine",
                   "playbook_engine", "trading_coach", "execution_intelligence",
                   "portfolio_intelligence", "continuous_learning"):
        assert engine in env
    assert env["continuous_learning"]["read_only"] is True


def test_capture_is_immutable_on_repeat_key(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    a = replay.capture({"ticker": "SPX"}, session_key="DUPE")
    b = replay.capture({"ticker": "SPX"}, session_key="DUPE")
    assert a["created"] is True
    assert b["created"] is False
    assert b["status"] == "IMMUTABLE_EXISTS"
    assert b["session_id"] == a["session_id"]


def test_timeline_is_ordered_and_has_evidence(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    out = replay.capture({"ticker": "SPX"}, session_key="T1")
    tl = replay.timeline(out["session_id"])
    events = tl["events"]
    assert events, "timeline should not be empty"
    frame_indices = [e["frame_index"] for e in events]
    assert frame_indices == sorted(frame_indices)
    times = [e["event_at"] for e in events]
    assert times == sorted(times)
    for e in events:
        assert "source_engine" in e
        assert "supporting_evidence" in e and "contradicting_evidence" in e
    # canonical order is respected for the event types that appear
    seen = [e["event_type"] for e in events]
    order = {t: i for i, t in enumerate(replay.EVENT_ORDER)}
    ranks = [order[t] for t in seen if t in order]
    assert ranks == sorted(ranks)


def test_navigation_step_and_jump(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    out = replay.capture({"ticker": "SPX"}, session_key="N1")
    sid = out["session_id"]
    fwd = replay.navigate(sid, action="STEP_FORWARD", cursor=0)
    assert fwd["cursor"] == 1
    back = replay.navigate(sid, action="STEP_BACKWARD", cursor=1)
    assert back["cursor"] == 0
    play = replay.navigate(sid, action="PLAY", cursor=0)
    assert play["playing"] is True and len(play["frames"]) == play["frame_count"]
    jump = replay.navigate(sid, action="JUMP_REGIME_TRANSITION", cursor=0)
    assert jump["current_frame"]["event_type"] == "REGIME_TRANSITION"


def test_simulator_isolation_does_not_write_history(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    out = replay.capture({"ticker": "SPX"}, session_key="SIM1")
    before = replay.list_sessions()["count"]
    sim = replay.simulate(out["session_id"], {"type": "ALTERNATIVE_SIZING", "size_multiplier": 0.5})
    after = replay.list_sessions()["count"]
    assert sim["ok"] is True
    assert sim["history_modified"] is False
    assert sim["records_written"] == 0
    assert before == after  # no new sessions created by simulation
    # session integrity hash unchanged after simulation
    s1 = replay.session(out["session_id"])["integrity_hash"]
    assert s1 == out["integrity_hash"]


def test_simulator_alternative_exits_math(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    out = replay.capture({"ticker": "SPX"}, session_key="SIM2")
    sim = replay.simulate(out["session_id"], {
        "type": "ALTERNATIVE_EXITS", "entry": 100, "baseline_exit": 110,
        "alternative_exit": 120, "risk_per_unit": 10})
    assert sim["comparison"]["baseline"]["r_multiple"] == 1.0
    assert sim["comparison"]["alternative"]["r_multiple"] == 2.0
    assert sim["comparison"]["delta"]["r_multiple"] == 1.0


def test_trade_replay_safe_without_decision(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    out = replay.capture({"ticker": "SPX"}, session_key="TR1")
    tr = replay.trade(out["session_id"])
    assert tr["ok"] is True
    assert "entry_thesis" in tr["trade_replay"]
    assert tr["production_effect"] == "NONE"


def test_missing_session_handled(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert replay.session("nope")["status"] == "NOT_FOUND"
    assert replay.timeline("nope")["status"] == "NOT_FOUND"
    assert replay.simulate("nope", {"type": "ALTERNATIVE_SIZING"})["status"] == "NOT_FOUND"

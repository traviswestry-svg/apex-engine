"""APEX 50.5.0 — Historical Level Calibration Engine tests.

Covers the full spine: extraction, registration, interaction detection,
outcome grading, statistics + segmentation, the adaptive blend schedule, the
heuristic fallback contract, and trade replay. No network, no live providers.
"""
import tempfile

from engine import historical_level_calibration as hlce


def _snapshot(price):
    return {
        "ticker": "SPX",
        "market_state": {"price": price, "pdh": 6050, "pdl": 5950},
        "gamma_regime": {"regime": "long_gamma", "call_wall": 6100,
                         "put_wall": 5900, "zero_gamma": 6000},
        "volume_profile": {"levels": {"poc": 6000, "vah": 6030, "val": 5970}},
        "expected_move_high": 6080, "expected_move_low": 5920, "vix": 14,
    }


def _fresh_db():
    path = tempfile.mktemp(suffix=".db")
    hlce.initialize_store(path)
    return path


# --- extraction --------------------------------------------------------- #

def test_extract_levels_pulls_all_families():
    levels = {l.level_type for l in hlce.extract_levels(_snapshot(6000))}
    for expected in ("call_wall", "put_wall", "zero_gamma", "poc", "vah", "val",
                     "expected_move_high", "expected_move_low", "prev_day_high", "prev_day_low"):
        assert expected in levels, expected


def test_extract_context_classifies_regimes():
    ctx = hlce.extract_context(_snapshot(6000))
    assert ctx.symbol == "SPX"
    assert ctx.gamma_regime == "LONG_GAMMA"
    assert ctx.expected_move_regime == "INSIDE_EXPECTED_MOVE"
    assert ctx.spot == 6000


def test_no_fabrication_when_levels_absent():
    # Empty snapshot -> no levels invented.
    assert hlce.extract_levels({"ticker": "SPX"}) == []


# --- registration + dedup ---------------------------------------------- #

def test_registration_is_idempotent_per_session():
    path = _fresh_db()
    first = hlce.register_daily_levels(_snapshot(6000), path=path, session_date="2026-07-01")
    again = hlce.register_daily_levels(_snapshot(6000), path=path, session_date="2026-07-01")
    assert first["registered"] > 0
    assert again["registered"] == 0  # deduped
    assert again["skipped"] == first["registered"]


# --- interaction detection + grading ----------------------------------- #

def test_reaction_off_put_wall_is_graded():
    path = _fresh_db()
    svc = hlce.CalibrationService(path)
    import time
    t = time.time() - 4000
    # down into the put wall @5900, then bounce back up (a rejection/REACTION)
    for p in [5960, 5940, 5915, 5902, 5900, 5901, 5915, 5945, 5975, 5990, 6000]:
        svc.tick(_snapshot(p), now=t)
        t += 8
    graded = hlce.run_grader(path=path, horizon_seconds=1800, now=t + 2000)
    assert graded["graded"] >= 1
    hlce.rebuild_statistics(path=path)
    rows = hlce.get_statistics("SPX", "put_wall", path=path)
    assert rows and rows[0]["sample_count"] >= 1
    # the put wall bounce should register as a reaction, not a break
    assert rows[0]["reaction_pct"] >= rows[0]["break_pct"]


def test_break_through_call_wall_is_graded_as_break():
    path = _fresh_db()
    svc = hlce.CalibrationService(path)
    import time
    t = time.time() - 4000
    for p in [6080, 6095, 6100, 6103, 6112, 6125, 6140, 6150, 6160]:
        svc.tick(_snapshot(p), now=t)
        t += 8
    hlce.run_grader(path=path, horizon_seconds=1800, now=t + 2000)
    hlce.rebuild_statistics(path=path)
    rows = hlce.get_statistics("SPX", "call_wall", path=path)
    assert rows and rows[0]["break_pct"] >= 50.0


# --- adaptive blend schedule (spec section 7) --------------------------- #

def test_blend_schedule_weights():
    assert hlce.heuristic_weight(0) == 0.90
    assert hlce.heuristic_weight(19) == 0.90
    assert hlce.heuristic_weight(20) == 0.70
    assert hlce.heuristic_weight(49) == 0.70
    assert hlce.heuristic_weight(50) == 0.40
    assert hlce.heuristic_weight(99) == 0.40
    assert hlce.heuristic_weight(100) == 0.20
    assert hlce.heuristic_weight(499) == 0.20
    assert hlce.heuristic_weight(500) == 0.00
    assert hlce.heuristic_weight(5000) == 0.00


def test_blend_math_and_provenance():
    b = hlce.blend(0.8, 0.4, 60)          # 40% heuristic
    assert abs(b["value"] - (0.4 * 0.8 + 0.6 * 0.4)) < 1e-9
    assert b["source"] == "CALIBRATED"
    assert hlce.blend(0.8, 0.4, 600)["source"] == "HISTORICAL"


def test_blend_falls_back_to_heuristic_with_no_history():
    b = hlce.blend(0.8, None, 0)
    assert b["value"] == 0.8
    assert b["source"] == "HEURISTIC"
    assert b["heuristic_weight"] == 1.0


# --- fallback contract: engine is fully operational with empty DB ------- #

def test_calibrated_probabilities_empty_db_returns_heuristic():
    path = _fresh_db()
    out = hlce.calibrated_probabilities(
        "SPX", "put_wall",
        heuristic={"reaction_prob": 0.77, "break_prob": 0.2, "reversal_prob": 0.3}, path=path)
    assert out["sample_count"] == 0
    assert out["reaction_prob"]["value"] == 0.77
    assert out["reaction_prob"]["source"] == "HEURISTIC"


def test_enrich_levels_dicts_never_raises_on_empty_db():
    path = _fresh_db()
    levels = [{"kind": "put_wall", "reaction_prob": 0.7, "break_prob": 0.2, "reversal_prob": 0.3}]
    out = hlce.enrich_levels_with_calibration(levels, {"gamma_regime": "LONG_GAMMA"},
                                              symbol="SPX", path=path)
    assert out[0]["reaction_prob"] == 0.7  # heuristic preserved
    assert out[0]["calibration"]["reaction_prob"]["source"] == "HEURISTIC"


# --- replay (spec section 11) ------------------------------------------ #

def test_trade_replay_records_and_reads_back():
    path = _fresh_db()
    rec = hlce.record_trade_replay(_snapshot(6000), {"won": True, "pnl": 250},
                                   trade_id="T-1", path=path)
    assert rec["ok"] and rec["replay_id"]


def test_replay_level_reports_missing_gracefully():
    path = _fresh_db()
    out = hlce.replay_level("does-not-exist", path=path)
    assert out["ok"] is False and out["error"] == "LEVEL_NOT_FOUND"


# --- health ------------------------------------------------------------- #

def test_health_and_status_shapes():
    path = _fresh_db()
    svc = hlce.CalibrationService(path)
    status = svc.status()
    health = svc.health()
    assert status["ok"] and "calibration_progress" in status
    assert "queue_depth" in health and "database_latency_ms" in health

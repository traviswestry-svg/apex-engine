"""Tests for APEX 25.5 Institutional Validation & Promotion Gate."""
import datetime as dt

import pytest

from engine import institutional_validation_promotion_v255 as validation
from engine import institutional_decision_review_v254 as review


def _iso(offset_s=0):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=offset_s)).isoformat()


def _snapshot(direction="BULLISH", confidence=82):
    now = _iso()
    return {
        "as_of": now, "symbol": "SPX", "decision_id": "dec_val_001",
        "direction": direction, "confidence": confidence, "market_regime": "TREND",
        "setup_family": "opening_drive",
        "market_state": {"spx": 5200.0, "as_of": now, "bias": direction, "regime": "TREND"},
        "institutional_intelligence": {"as_of": now, "institutional_bias": direction, "ici_score": 78},
        "flow_intelligence": {"as_of": now, "direction": direction, "score": 72},
        "dealer_positioning": {"as_of": now, "bias": direction},
        "multi_timeframe": {"as_of": now, "alignment_score": 70},
        "market_memory": {"as_of": now}, "historical_similarity": {"as_of": now},
        "confidence_calibration": {"as_of": now},
    }


# --------------------------------------------------------------------------- #
# Status / aggregate
# --------------------------------------------------------------------------- #
def test_status_shadow_enforced():
    s = validation.status()
    assert s["shadow_mode_enforced"] is True
    assert s["nothing_self_promotes"] is True
    assert s["production_effect"] == "NONE"
    assert len(s["lifecycle_stages"]) == 11


def test_build_validation_shape():
    result = validation.build_validation(_snapshot())
    assert result["ok"] is True
    assert result["production_effect"] == "NONE"
    for key in ("lifecycle_validation", "supervisor", "dashboard"):
        assert key in result
    assert result["guardrails"]["nothing_self_promotes"] is True


# --------------------------------------------------------------------------- #
# 25.5.1 Lifecycle validator
# --------------------------------------------------------------------------- #
def test_lifecycle_live_snapshot_valid():
    result = validation.validate_lifecycle(_snapshot(), realized={"matured": False})
    # Immature outcome/trade are not critical defects.
    assert result["valid"] is True
    assert "market_data" in result["stages"]
    assert len(result["audit_log"]) == 11


def test_lifecycle_missing_market_data_is_critical():
    snap = _snapshot()
    snap.pop("market_state")
    result = validation.validate_lifecycle(snap, realized={"matured": False})
    assert any(d.startswith("MISSING_CRITICAL_STAGE:market_data") for d in result["defects"])
    assert result["valid"] is False


def test_lifecycle_orphaned_decision_id(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_DECISION_REVIEW_DB", str(tmp_path / "r.db"))
    result = validation.validate_lifecycle(decision_id="does_not_exist")
    assert result["status"] == "ORPHANED"
    assert result["valid"] is False


# --------------------------------------------------------------------------- #
# 25.5.2 Supervisor
# --------------------------------------------------------------------------- #
def test_supervisor_reports_all_engines():
    sup = validation.supervise(_snapshot())
    assert sup["shadow_mode_enforced"] is True
    for engine in validation.SUPERVISED_ENGINES:
        assert engine in sup["engines"]
        assert sup["engines"][engine]["state"] in ("SHADOW", "DISABLED", "PAUSED", "PROMOTED", "ACTIVE")


def test_supervisor_engines_are_shadow_by_default():
    sup = validation.supervise(_snapshot())
    assert sup["engines"]["forecast"]["state"] == "SHADOW"
    assert sup["engines"]["calibration"]["state"] == "SHADOW"


# --------------------------------------------------------------------------- #
# 25.5.4 Replay verification (hash equality)
# --------------------------------------------------------------------------- #
def test_replay_verify_matches_stored(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_DECISION_REVIEW_DB", str(tmp_path / "r.db"))
    lc = review.build_lifecycle_snapshot(_snapshot())
    review.record_decision(lifecycle=lc)
    result = validation.verify_replay(lc["decision_id"])
    assert result["ok"] is True
    assert result["match"] is True
    assert result["stored_integrity_hash"] == result["recomputed_integrity_hash"]


def test_replay_verify_reconstruction_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_DECISION_REVIEW_DB", str(tmp_path / "r.db"))
    result = validation.verify_replay("missing_decision")
    assert result["match"] is False
    assert result["status"] == "RECONSTRUCTION_FAILED"


# --------------------------------------------------------------------------- #
# 25.5.7 Production safety gate
# --------------------------------------------------------------------------- #
def test_safety_blocks_on_missing_critical_evidence():
    snap = _snapshot()
    snap.pop("market_state")
    snap.pop("institutional_intelligence")
    safety = validation.promotion_safety("forecast", snap)
    assert safety["safe_to_promote"] is False
    assert safety["blockers"]


def test_safety_blocks_forecast_low_sample(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_DECISION_FORECAST_DB", str(tmp_path / "f.db"))
    safety = validation.promotion_safety("forecast", _snapshot())
    assert safety["safe_to_promote"] is False
    assert any("sample" in b.lower() for b in safety["blockers"])


# --------------------------------------------------------------------------- #
# 25.5.5 Promotion engine (governed workflow, nothing self-promotes)
# --------------------------------------------------------------------------- #
def test_promotion_blocked_when_unsafe(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_VALIDATION_DB", str(tmp_path / "v.db"))
    monkeypatch.setenv("APEX_DECISION_FORECAST_DB", str(tmp_path / "f.db"))
    result = validation.propose_promotion("forecast", actor="travis", payload=_snapshot())
    # No sample -> safety blocks the proposal.
    assert result["ok"] is False
    assert result["status"] == "BLOCKED"


def test_promotion_illegal_transition(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_VALIDATION_DB", str(tmp_path / "v.db"))
    # From SHADOW, approving directly is illegal (must PROPOSE -> REVIEW -> APPROVE).
    result = validation._set_state("learning", "APPROVED", "travis", "")
    assert result["ok"] is False
    assert result["status"] == "ILLEGAL_TRANSITION"


def test_promotion_to_production_requires_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_VALIDATION_DB", str(tmp_path / "v.db"))
    monkeypatch.delenv("APEX_PROMOTION_APPROVED", raising=False)
    # Move learning through the workflow to APPROVED via safe path.
    # learning has no forecast/calibration sample gate, so safety passes with healthy snapshot.
    snap = _snapshot()
    validation.propose_promotion("learning", actor="t", payload=snap)
    validation.review_promotion("learning", actor="t")
    validation.approve_promotion("learning", actor="t", payload=snap)
    result = validation.promote_to_production("learning", actor="t", payload=snap)
    assert result["ok"] is False
    assert result["status"] == "OPERATOR_APPROVAL_REQUIRED"


def test_promotion_overview_defaults_shadow(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_VALIDATION_DB", str(tmp_path / "v.db"))
    overview = validation.promotion_overview(_snapshot())
    assert overview["engines"]["forecast"]["state"] == "SHADOW"


# --------------------------------------------------------------------------- #
# 25.5.3 Dashboard + 25.5.6 Reports
# --------------------------------------------------------------------------- #
def test_dashboard_panels():
    dash = validation.dashboard(_snapshot())
    for panel in ("forecast_panel", "confidence_panel", "evidence_health_panel", "promotion_panel"):
        assert panel in dash
    assert dash["shadow_mode_enforced"] is True


def test_all_reports(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_VALIDATION_DB", str(tmp_path / "v.db"))
    monkeypatch.setenv("APEX_DECISION_FORECAST_DB", str(tmp_path / "f.db"))
    for kind in validation.REPORT_KINDS:
        rep = validation.build_report(kind, _snapshot())
        assert rep["ok"] is True
        assert rep["report"] == kind


def test_report_unknown():
    assert validation.build_report("nope")["ok"] is False


# --------------------------------------------------------------------------- #
# Mission Control
# --------------------------------------------------------------------------- #
def test_mission_control_group():
    result = validation.build_validation(_snapshot())
    group = validation.mission_control_group(result)
    assert group["group"] == "INSTITUTIONAL_VALIDATION"
    assert group["shadow_mode_enforced"] is True
    assert group["production_effect"] == "NONE"

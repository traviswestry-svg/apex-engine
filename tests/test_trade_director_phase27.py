import os

import pytest

from engine.trade_director_change_control import (
    build_change_control,
    propose_change,
    review_change,
    validate_change,
    verify_change_integrity,
)


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_CHANGE_CONTROL_DB", str(tmp_path / "phase27.db"))


def _proposal():
    return propose_change({
        "title": "Phase 27 integration",
        "summary": "Add confirmation-gated institutional change control.",
        "phase": "27",
        "change_type": "FEATURE",
        "risk_level": "MEDIUM",
        "requested_by": "architect",
        "target_version": "27.0",
        "changed_files": ["app.py", "engine/trade_director_change_control.py"],
        "rollback_plan": "Restore the prior repository artifact and database snapshot.",
        "compatibility_notes": "Additive APIs and dashboard panel; no existing route removed.",
        "validation_plan": {"compile": True, "tests": True, "dashboard": True},
    })


def test_proposal_is_deterministic_and_append_only():
    first = _proposal()
    second = _proposal()
    assert first["change_id"] == second["change_id"]
    assert first["status"] == "DRAFT"
    assert verify_change_integrity(first["change_id"])["status"] == "VERIFIED"


def test_validation_and_independent_approval_gate():
    item = _proposal()
    validated = validate_change(item["change_id"], {
        "python_compilation": True,
        "regression_tests": True,
        "api_validation": True,
        "dashboard_validation": True,
        "zip_integrity": True,
        "test_total": 42,
        "test_failures": 0,
    }, "validator")
    assert validated["status"] == "AWAITING_APPROVAL"
    with pytest.raises(ValueError, match="independent reviewer"):
        review_change(item["change_id"], "APPROVE", "architect", "self approval")
    approved = review_change(item["change_id"], "APPROVE", "release_manager", "evidence verified")
    assert approved["status"] == "APPROVED"


def test_failed_validation_cannot_be_approved():
    item = _proposal()
    failed = validate_change(item["change_id"], {
        "python_compilation": True,
        "regression_tests": False,
        "api_validation": True,
        "dashboard_validation": True,
        "zip_integrity": True,
        "test_total": 10,
        "test_failures": 1,
    }, "validator")
    assert failed["status"] == "VALIDATION_FAILED"
    with pytest.raises(ValueError, match="pass validation"):
        review_change(item["change_id"], "APPROVE", "release_manager", "not ready")


def test_change_control_is_observational_only():
    center = build_change_control({"institutional_command_center": {"system_state": "GREEN"}})
    assert center["version"] == "PHASE_27"
    assert center["controls"]["automatic_deployment"] is False
    assert center["controls"]["runtime_mutation"] is False
    assert center["controls"]["broker_access"] is False


def test_app_and_dashboard_integration_are_present():
    root = os.path.dirname(os.path.dirname(__file__))
    app_text = open(os.path.join(root, "app.py"), encoding="utf-8").read()
    html = open(os.path.join(root, "templates", "assistant.html"), encoding="utf-8").read()
    for route in (
        "/api/change-control/status", "/api/change-control/history",
        "/api/change-control/propose", "/api/change-control/validate",
        "/api/change-control/review", "/api/change-control/integrity",
    ):
        assert route in app_text
    assert "TRADE DIRECTOR PHASE 27" in html
    assert "renderChangeControl" in html

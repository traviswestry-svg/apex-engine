"""HTTP surface for the APEX Dynamic State panel.

Read-only. Reshapes the three dynamic-state signals already present on the Data
Bus (plus the persisted residual-pressure memory) into one block for the
dashboard. No provider I/O, no recomputation.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from flask import jsonify

from .dynamic_state import build_dynamic_state
from .dynamic_state_policy import evaluate_dynamic_state_policy


def register_dynamic_state_routes(app, *, last_result_provider: Optional[Callable[[], Dict[str, Any]]] = None,
                                  scanner_state_provider: Optional[Callable[[], Dict[str, Any]]] = None) -> None:
    def _lr() -> Dict[str, Any]:
        try:
            return (last_result_provider() if callable(last_result_provider) else {}) or {}
        except Exception:
            return {}

    def _ss() -> Dict[str, Any]:
        try:
            return (scanner_state_provider() if callable(scanner_state_provider) else {}) or {}
        except Exception:
            return {}

    @app.get("/api/dynamic-state")
    def dynamic_state():
        lr = _lr()
        state = build_dynamic_state(lr, _ss())
        state["alert_policy"] = evaluate_dynamic_state_policy(lr, dynamic_state=state)
        return jsonify(state)

    @app.get("/api/dynamic-state/calibration")
    def dynamic_state_calibration():
        try:
            from .dynamic_state_outcome_calibration import calibration_summary
            from .dynamic_state_calibration_governance import governance_overview
            from .evidence_pipeline import DEFAULT_DB
            out = calibration_summary(DEFAULT_DB)
            out["promotion_governance"] = governance_overview(DEFAULT_DB)
            return jsonify(out)
        except Exception as exc:
            return jsonify({"ok": False, "status": "UNAVAILABLE", "error": str(exc),
                            "execution_authority": False}), 200

    @app.get("/api/dynamic-state/calibration-governance")
    def dynamic_state_calibration_governance():
        try:
            from .dynamic_state_calibration_governance import governance_overview
            from .evidence_pipeline import DEFAULT_DB
            return jsonify(governance_overview(DEFAULT_DB))
        except Exception as exc:
            return jsonify({"ok": False, "status": "UNAVAILABLE", "error": str(exc),
                            "production_effect": "NONE", "execution_authority": False}), 200

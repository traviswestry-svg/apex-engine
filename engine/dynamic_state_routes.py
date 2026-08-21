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

"""engine/confirmation_scanner_routes.py — APEX 11.0C Module 8 routes."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from flask import jsonify, request

from engine.confirmation_scanner import CONFIRMATION_SCANNER_VERSION, scan_confirmation


def _extract_spx_direction(bus: Optional[Dict[str, Any]]) -> Any:
    """Pull the SPX decision direction the scanner will confirm — never form one."""
    if not isinstance(bus, dict):
        return None
    for path in ("approved_side", "leading_conviction_side", "decision"):
        v = bus.get(path)
        if isinstance(v, str) and v:
            return v
    flow = bus.get("flow") if isinstance(bus.get("flow"), dict) else {}
    return flow.get("approved_side") or flow.get("bias")


def _extract_assets(bus: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Collect confirmation-asset readings already on the bus, if present."""
    if not isinstance(bus, dict):
        return {}
    rot = bus.get("rotation")
    assets: Dict[str, Any] = {}
    if isinstance(rot, dict):
        assets["rotation"] = rot.get("regime") or rot.get("state")
    confirm = bus.get("confirmation_assets")
    if isinstance(confirm, dict):
        assets.update(confirm)
    return assets


def register_confirmation_scanner_routes(
    app,
    *,
    last_result_provider: Optional[Callable[[], Dict[str, Any]]] = None,
) -> None:

    @app.route("/api/confirmation_scan", methods=["GET"])
    def _confirmation_scan():
        try:
            bus = last_result_provider() if last_result_provider else None
            payload = scan_confirmation(
                spx_direction=_extract_spx_direction(bus),
                assets=_extract_assets(bus))
            return jsonify(payload), (200 if payload.get("available") else 503)
        except Exception as e:  # pragma: no cover
            return jsonify({"available": False, "ok": True, "degraded": True,
                            "version": CONFIRMATION_SCANNER_VERSION, "error": str(e)}), 503

    @app.route("/api/confirmation_scan/health", methods=["GET"])
    def _confirmation_scan_health():
        return jsonify({"ok": True, "version": CONFIRMATION_SCANNER_VERSION}), 200

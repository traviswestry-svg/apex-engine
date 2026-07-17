"""APEX 10 Sprint 7 institutional-state API routes."""
from __future__ import annotations

from flask import jsonify, request

from .decision_provenance import get_snapshot
from .institutional_state import VERSION, build_institutional_state


def register_institutional_state_routes(app, *, last_result_provider=None) -> None:
    def _current():
        return last_result_provider() if callable(last_result_provider) else {}

    def _payload():
        ticker = (request.args.get("ticker") or "SPX").upper()
        sample_id = request.args.get("sample_id")
        source = _current()
        replay = None
        if sample_id:
            replay = get_snapshot(sample_id)
            if replay and replay.get("integrity_ok"):
                source = (replay.get("payload") or {}).get("decision_output") or {}
        state = build_institutional_state(current_result=source, ticker=ticker, sample_id=sample_id)
        if replay is not None:
            state["replay"] = {
                "available": True,
                "snapshot_id": replay.get("snapshot_id"),
                "integrity_ok": replay.get("integrity_ok"),
                "payload_hash": replay.get("payload_hash"),
            }
        return state

    @app.get("/api/institutional_state")
    def _institutional_state():
        return jsonify({"ok": True, "institutional_state": _payload(), "version": VERSION})

    @app.get("/api/evidence_graph")
    def _evidence_graph():
        p = _payload()
        return jsonify({"ok": True, "ticker": p["ticker"], "state_hash": p["state_hash"], "evidence_graph": p["evidence_graph"]})

    @app.get("/api/decision_trace")
    def _decision_trace():
        p = _payload()
        return jsonify({"ok": True, "ticker": p["ticker"], "state_hash": p["state_hash"], "decision_trace": p["decision_trace"], "replay": p.get("replay")})

    @app.get("/api/market_story")
    def _market_story():
        p = _payload()
        return jsonify({"ok": True, "ticker": p["ticker"], "state_hash": p["state_hash"], "market_story": p["market_story"]})

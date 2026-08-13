"""engine/flow_clusters_routes.py — APEX 9 Step 3 API surface.

Mirrors flow_classifier_routes.py: isolated, read-only, never 500s the dashboard.

Routes
------
GET /api/flow_clusters          — clusters of classified prints for a ticker set.
GET /api/flow_clusters/health   — config, versions, and the metrics this layer
                                  cannot derive (so the UI states limits rather
                                  than implying completeness).

The pipeline is strictly: existing tape → classifier → clusterer. Clustering
consumes **classified events**, never raw provider rows, per spec. Nothing
upstream is modified; /api/flow_tape and /api/flow_classifier keep their shapes.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Callable, Dict, List, Optional

from flask import jsonify, request

from .flow_classifier import classify_flow_events
from .flow_confirmation import TRACKER, market_snapshot
from .flow_clusters import (
    CLUSTER_CONFIG_VERSION,
    CLUSTER_VERSION,
    FLOW_CLUSTERING_ENABLED,
    build_flow_clusters,
    health as clusters_health,
)


def _now_et_secs() -> Optional[int]:
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo("America/New_York")
        n = _dt.datetime.now(tz)
        return n.hour * 3600 + n.minute * 60 + n.second
    except Exception:  # pragma: no cover
        return None


def _empty(note: str) -> Dict[str, Any]:
    return {"available": False, "note": note, "count": 0, "clusters": [],
            "singletons": [], "cluster_version": CLUSTER_VERSION,
            "cluster_config_version": CLUSTER_CONFIG_VERSION}


def register_flow_clusters_routes(
    app,
    *,
    flow_tape_provider: Optional[Callable[[List[str], float], Dict[str, Any]]] = None,
    last_result_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    default_ticker: str = "SPX",
) -> None:
    """Attach clustering routes. Providers are injected — this module never
    contacts a data provider itself."""

    @app.route("/api/flow_clusters")
    def _flow_clusters():
        try:
            if not FLOW_CLUSTERING_ENABLED:
                return jsonify({"ok": True, "flow_clusters": _empty(
                    "Flow clustering disabled (FLOW_CLUSTERING_ENABLED=false).")})
            tickers = [t.strip().upper() for t in
                       (request.args.get("tickers") or default_ticker).split(",") if t.strip()]
            try:
                min_premium = float(request.args.get("min_premium") or 0)
            except (TypeError, ValueError):
                min_premium = 0.0
            min_prints = request.args.get("min_prints")
            try:
                min_prints = int(min_prints) if min_prints else None
            except (TypeError, ValueError):
                min_prints = None

            if flow_tape_provider is None:
                return jsonify({"ok": True, "flow_clusters": _empty(
                    "No flow source wired — nothing to cluster.")})

            tape = flow_tape_provider(tickers, min_premium) or {}
            rows = tape.get("rows") or []
            if not rows:
                payload = _empty(tape.get("message") or "No flow rows available to cluster.")
                payload["available"] = True
                payload["upstream_status"] = tape.get("status")
                return jsonify({"ok": True, "tickers": tickers, "flow_clusters": payload})

            spot = None
            if last_result_provider:
                lr = last_result_provider() or {}
                ms = lr.get("market_state") or {}
                try:
                    spot = float(ms.get("price")) if ms.get("price") else None
                except (TypeError, ValueError):
                    spot = None

            classified = classify_flow_events(rows, spot=spot, as_of_secs=_now_et_secs())
            result = build_flow_clusters(classified["events"], min_prints=min_prints)
            # Polling this endpoint supplies later observations.  Confirmation is
            # stored separately and never backdated into the decision-time vector.
            lr = last_result_provider() if last_result_provider else {}
            events_by_id = {e.get("event_id"): e for e in classified.get("events", [])}
            snap = market_snapshot(lr or {})
            result["clusters"] = TRACKER.observe(result.get("clusters", []), events_by_id, snap)
            result["singletons"] = TRACKER.observe(result.get("singletons", []), events_by_id, snap)
            result["upstream_status"] = tape.get("status")
            result["classifier_version"] = classified.get("classifier_version")
            result["events_classified"] = classified.get("count")
            return jsonify({"ok": True, "tickers": tickers, "flow_clusters": result})
        except Exception as e:
            return jsonify({"ok": True, "flow_clusters": _empty(
                f"flow clusters route recovered: {e}")})

    @app.route("/api/flow_clusters/health")
    def _flow_clusters_health():
        try:
            h = clusters_health()
            h["ok"] = True
            return jsonify({"ok": True, "health": h})
        except Exception as e:
            return jsonify({"ok": True, "health": {
                "ok": False, "enabled": False, "note": f"health recovered: {e}",
                "cluster_version": CLUSTER_VERSION}})

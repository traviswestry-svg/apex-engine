"""engine/feature_store_routes.py — APEX 9 Step 5a diagnostics.

Health only. There is deliberately no route that serves feature vectors joined to
labels: the two-record rule is enforced in the data layer, and an endpoint that
hands back a flat row would quietly undo it.

GET /api/feature_store/health — row counts, session coverage, and — the number
that actually governs whether Step 5 is ready — how many sessions of history
exist.
"""
from __future__ import annotations

from typing import Any, Dict

from flask import jsonify

from .feature_store import (
    FEATURE_SCHEMA_VERSION,
    FORBIDDEN_FEATURE_NAMES,
    FORBIDDEN_FEATURE_SUBSTRINGS,
    LABEL_SCHEMA_VERSION,
    sample_quality,
)
from . import feature_store_db


def register_feature_store_routes(app, *, track: bool = True) -> None:
    if track:
        feature_store_db.init_db()

    @app.route("/api/feature_store/health")
    def _feature_store_health():
        try:
            h: Dict[str, Any] = feature_store_db.health()
            sess = feature_store_db.sessions("features")
            h["sessions_covered"] = len(sess)
            h["first_session"] = sess[0] if sess else None
            h["last_session"] = sess[-1] if sess else None
            h["feature_schema_version"] = FEATURE_SCHEMA_VERSION
            h["label_schema_version"] = LABEL_SCHEMA_VERSION
            h["forbidden_feature_names"] = sorted(FORBIDDEN_FEATURE_NAMES)
            h["forbidden_feature_substrings"] = list(FORBIDDEN_FEATURE_SUBSTRINGS)
            h["global_sample_quality"] = sample_quality(h.get("feature_rows") or 0)
            h["readiness"] = (
                "Sample counts here are GLOBAL. Similarity requires counts in a matched "
                "neighbourhood, which are far smaller — a store with 200 rows spread over "
                "72 regime cells has ~3 per cell and supports no edge claim. Step 5's "
                "similarity engine must grade on the matched count, never on this total.")
            h["ok"] = True
            return jsonify({"ok": True, "health": h})
        except Exception as e:
            return jsonify({"ok": True, "health": {
                "ok": False, "note": f"health recovered: {e}",
                "feature_schema_version": FEATURE_SCHEMA_VERSION}})

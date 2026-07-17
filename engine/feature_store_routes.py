"""engine/feature_store_routes.py — APEX 9 Step 5a/5a.2 diagnostics.

Routes
------
GET /api/feature_store/health              — counts, session coverage, guard lists
GET /api/feature_store/samples             — feature vectors ONLY (no labels)
GET /api/feature_store/sample/<sample_id>  — one record; pre_decision / post_outcome
                                             kept in separate named objects
GET /api/feature_store/coverage            — matched-neighbourhood counts. THE
                                             number that gates 5b.

WHAT IS DELIBERATELY ABSENT
---------------------------
There is no `/api/feature_store/training_data` returning flat feature+label rows.
That endpoint would be the leak: it would make `load_training_pairs()`'s
train/eval split enforcement bypassable with a URL. Bulk access for 5b goes
through that function, in-process, or not at all.

A human reading one record is not the leak — a bulk flat export fed to a trainer
is. Hence /sample/<id> exists and never merges the two halves.
"""
from __future__ import annotations

from typing import Any, Dict

from flask import jsonify, request

from .feature_store import (
    FEATURE_SCHEMA_VERSION,
    FORBIDDEN_FEATURE_NAMES,
    FORBIDDEN_FEATURE_SUBSTRINGS,
    LABEL_SCHEMA_VERSION,
    sample_quality,
)
from . import feature_store_db

try:
    from .feature_store_writer import health as writer_health
except Exception:  # pragma: no cover
    writer_health = None  # type: ignore[assignment]


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
            if writer_health is not None:
                h["writer"] = writer_health()
            h["readiness"] = (
                "Sample counts here are GLOBAL. Similarity requires counts in a matched "
                "neighbourhood, which are far smaller — see /api/feature_store/coverage, "
                "which is the number that actually gates the similarity engine.")
            h["ok"] = True
            return jsonify({"ok": True, "health": h})
        except Exception as e:
            return jsonify({"ok": True, "health": {
                "ok": False, "note": f"health recovered: {e}",
                "feature_schema_version": FEATURE_SCHEMA_VERSION}})

    @app.route("/api/feature_store/samples")
    def _feature_store_samples():
        try:
            session = (request.args.get("session") or "").strip() or None
            try:
                limit = int(request.args.get("limit") or 50)
                offset = int(request.args.get("offset") or 0)
            except (TypeError, ValueError):
                limit, offset = 50, 0
            rows = feature_store_db.list_features(session_date=session, limit=limit,
                                                  offset=offset)
            return jsonify({"ok": True, "samples": rows, "count": len(rows),
                            "session": session,
                            "note": ("Pre-decision feature vectors only — labels are not "
                                     "read by this route. feature_availability carries each "
                                     "field's availability timestamp and lag; a large "
                                     "max_feature_lag_seconds means the decision was informed "
                                     "by a stale frame.")})
        except Exception as e:
            return jsonify({"ok": True, "samples": [], "count": 0,
                            "note": f"samples route recovered: {e}"})

    @app.route("/api/feature_store/sample/<sample_id>")
    def _feature_store_sample(sample_id):
        try:
            s = feature_store_db.get_sample(sample_id)
            if not s:
                return jsonify({"ok": True, "sample": None,
                                "note": f"No sample {sample_id!r}."})
            return jsonify({"ok": True, "sample": s})
        except Exception as e:
            return jsonify({"ok": True, "sample": None,
                            "note": f"sample route recovered: {e}"})

    @app.route("/api/feature_store/coverage")
    def _feature_store_coverage():
        try:
            dims_raw = (request.args.get("dims") or "").strip()
            dims = tuple(d.strip() for d in dims_raw.split(",") if d.strip()) or None
            sess_raw = (request.args.get("sessions") or "").strip()
            sessions = [s.strip() for s in sess_raw.split(",") if s.strip()] or None
            kw: Dict[str, Any] = {"sessions": sessions}
            if dims:
                kw["dims"] = dims
            cov = feature_store_db.neighbourhood_coverage(**kw)
            return jsonify({"ok": True, "coverage": cov})
        except Exception as e:
            return jsonify({"ok": True, "coverage": {"cells": [], "total_samples": 0},
                            "note": f"coverage route recovered: {e}"})

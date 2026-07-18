"""engine/release_routes.py — APEX 11.0A: read-only release + integrity endpoints.

Exposes the release_manager surface over HTTP. Every route is GET-only and
non-mutating; POST returns 405 by virtue of not being registered. Each handler is
wrapped so a storage hiccup returns a well-formed 503 with ok:true rather than a
500 — this surface reports health, so it must stay up precisely when something is
wrong underneath it.

`ok` here means "this endpoint answered", not "everything is healthy". Health
lives in the payload: migration_status.ready, data_integrity.statistics_supportable.
An endpoint reporting an empty store is working correctly.
"""
from __future__ import annotations

from typing import Any, Callable, Dict

from flask import jsonify

from engine.release_manager import (APPLICATION_VERSION, DATABASE_VERSION, FEATURES,
                                    SEMANTIC_VERSION, data_integrity, migration_status,
                                    release_metadata)

RELEASE_ROUTES_VERSION = "11.0.0_RELEASE_ROUTES"


def _safe(fn: Callable[[], Dict[str, Any]]):
    """Report-or-degrade: never let an integrity endpoint 500.

    A 503 still carries ok:true — the endpoint answered — with the failure in the
    body. Status distinguishes "answered, healthy" (200) from "answered, degraded"
    (503) without ever throwing.
    """
    try:
        payload = fn()
        payload.setdefault("ok", True)
        healthy = payload.get("ready", payload.get("statistics_supportable", True))
        return jsonify(payload), (200 if healthy else 503)
    except Exception as e:  # pragma: no cover
        return jsonify({"ok": True, "degraded": True, "error": str(e)}), 503


def register_release_routes(app, **_kwargs) -> None:
    """Register the /api/system/* read-only surface."""

    @app.route("/api/system/version", methods=["GET"])
    def _system_version():
        return jsonify({
            "ok": True,
            "version": SEMANTIC_VERSION,
            "application_version": APPLICATION_VERSION,
            "database_version": DATABASE_VERSION,
        }), 200

    @app.route("/api/system/build", methods=["GET"])
    def _system_build():
        m = release_metadata()
        return jsonify({
            "ok": True,
            "build": m["build"],
            "commit": m["commit"],
            "commit_known": m["commit_known"],
            "environment": m["environment"],
            "generated_at": m["generated_at"],
        }), 200

    @app.route("/api/system/features", methods=["GET"])
    def _system_features():
        return jsonify({"ok": True, "features": list(FEATURES),
                        "count": len(FEATURES)}), 200

    @app.route("/api/system/migrations", methods=["GET"])
    def _system_migrations():
        return _safe(migration_status)

    @app.route("/api/system/integrity", methods=["GET"])
    def _system_integrity():
        return _safe(data_integrity)

    @app.route("/api/system/release", methods=["GET"])
    def _system_release():
        return _safe(release_metadata)


# Backward-compatible name: app.py imports register_release_manager_routes.
def register_release_manager_routes(app, **kwargs) -> None:
    register_release_routes(app, **kwargs)

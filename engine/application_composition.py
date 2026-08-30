"""APEX 22.5 application composition boundary.

The legacy production module still owns compatibility route registration. This
factory provides a stable WSGI/test entry point while future blueprints are
extracted incrementally from app.py.
"""
from __future__ import annotations
from typing import Any, Dict

from . import storage_retention
from . import trigger_observatory
from . import trigger_observatory_routes

VERSION = "69.7.1"


def create_app():
    # Canonical production composition boundary.  The legacy app module still
    # owns route registration today, but Render/Gunicorn now enters through this
    # factory so future extraction does not require a deployment-command change.
    from app import app
    app.config.setdefault("APEX_COMPOSITION_BOUNDARY", "engine.application_composition:create_app")
    app.config.setdefault("APEX_STABILIZATION_BUILD", "65.6.1")
    # APEX 69.4.3 storage-retention operational integration. Keep the audit
    # callable reachable from the canonical runtime without running DB scans
    # during application startup or changing trading behavior.
    app.config.setdefault("APEX_STORAGE_RETENTION_VERSION", storage_retention.VERSION)
    app.extensions.setdefault("apex_storage_retention_audit", storage_retention.audit)
    # APEX 69.7.1 production reachability boundary. app.py owns the actual
    # registration to preserve its duplicate-route guards; composition keeps
    # both observatory modules explicitly reachable from the canonical runtime
    # root and exposes their governed capabilities for runtime inspection.
    app.config.setdefault("APEX_TRIGGER_OBSERVATORY_VERSION", trigger_observatory.VERSION)
    app.extensions.setdefault("apex_trigger_observatory", trigger_observatory.capability)
    app.extensions.setdefault(
        "apex_trigger_observatory_routes_verify",
        trigger_observatory_routes.verify_registered,
    )
    return app


def route_inventory(application=None) -> Dict[str, Any]:
    app = application or create_app()
    routes = []
    for rule in sorted(app.url_map.iter_rules(), key=lambda item: (item.rule, item.endpoint)):
        routes.append({
            "rule": rule.rule,
            "endpoint": rule.endpoint,
            "methods": sorted(method for method in rule.methods if method not in {"HEAD", "OPTIONS"}),
        })
    return {"ok": True, "version": VERSION, "count": len(routes), "routes": routes}

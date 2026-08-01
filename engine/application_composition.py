"""APEX 22.5 application composition boundary.

The legacy production module still owns compatibility route registration. This
factory provides a stable WSGI/test entry point while future blueprints are
extracted incrementally from app.py.
"""
from __future__ import annotations
from typing import Any, Dict

VERSION = "65.4"


def create_app():
    # Canonical production composition boundary.  The legacy app module still
    # owns route registration today, but Render/Gunicorn now enters through this
    # factory so future extraction does not require a deployment-command change.
    from app import app
    app.config.setdefault("APEX_COMPOSITION_BOUNDARY", "engine.application_composition:create_app")
    app.config.setdefault("APEX_STABILIZATION_BUILD", "65.4")
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

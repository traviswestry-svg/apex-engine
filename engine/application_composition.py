"""APEX 22.5 application composition boundary.

The legacy production module still owns compatibility route registration. This
factory provides a stable WSGI/test entry point while future blueprints are
extracted incrementally from app.py.
"""
from __future__ import annotations
from typing import Any, Dict

VERSION = "15.5.0_PRE_23_HARDENING"


def create_app():
    from app import app
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

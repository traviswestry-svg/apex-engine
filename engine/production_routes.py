"""APEX 10 Sprint 8 production-readiness routes."""
from __future__ import annotations

from flask import jsonify
from .production_observability import COMPONENT_VERSION, VERSION, integration_health, metrics_snapshot


def register_production_routes(app, *, capability_provider=None) -> None:
    def _caps():
        return capability_provider() if callable(capability_provider) else {}

    @app.get('/api/system/metrics')
    def _system_metrics():
        return jsonify({'ok': True, 'metrics': metrics_snapshot(), 'version': VERSION, 'apex_version': VERSION, 'component_version': COMPONENT_VERSION, 'version_source': 'config/apex_release_manifest.json'})

    @app.get('/api/system/readiness')
    def _system_readiness():
        health = integration_health(capabilities=_caps())
        return jsonify({'ok': True, 'readiness': health, 'version': VERSION, 'apex_version': VERSION, 'component_version': COMPONENT_VERSION, 'version_source': 'config/apex_release_manifest.json'}), (200 if health['ready'] else 503)

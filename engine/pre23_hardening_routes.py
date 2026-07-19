"""Read-only APEX 22.5 hardening routes."""
from flask import jsonify
from .pre23_hardening import hardening_status, immutable_snapshot, persistence_inventory, route_assurance


def register_pre23_hardening_routes(app, last_result_provider):
    def current():
        value = last_result_provider() if callable(last_result_provider) else {}
        return value if isinstance(value, dict) else {}

    @app.get('/api/pre23-hardening/status')
    def pre23_status(): return jsonify(hardening_status(app))

    @app.get('/api/pre23-hardening/routes')
    def pre23_routes(): return jsonify(route_assurance(app))

    @app.get('/api/pre23-hardening/persistence')
    def pre23_persistence(): return jsonify(persistence_inventory())

    @app.get('/api/institutional-snapshot/status')
    def institutional_snapshot():
        snap = immutable_snapshot(current())
        return jsonify({'ok': True, 'version': '15.5.0_PRE_23_HARDENING', **snap})

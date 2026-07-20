"""HTTP routes for APEX 24.5 Institutional Command Center (read-only)."""
from flask import jsonify

from . import institutional_command_center_v245 as command_center

REQUIRED_ROUTES = (
    ("GET", "/api/command-center/status"),
    ("GET", "/api/command-center/overview"),
    ("GET", "/api/command-center/panel/<panel_id>"),
)


def verify_registered(app):
    present = {(m, str(rule)) for rule in app.url_map.iter_rules()
               for m in (rule.methods or set())}
    return [f"{m} {p}" for m, p in REQUIRED_ROUTES if (m, p) not in present]


def register_institutional_command_center_v245_routes(app, *, last_result_provider=None):
    def last():
        value = last_result_provider() if callable(last_result_provider) else {}
        return value if isinstance(value, dict) else {}

    @app.get('/api/command-center/status')
    def command_center_v245_status():
        return jsonify(command_center.status())

    @app.get('/api/command-center/overview')
    def command_center_v245_overview():
        return jsonify(command_center.build_command_center(last()))

    @app.get('/api/command-center/panel/<panel_id>')
    def command_center_v245_panel(panel_id):
        return jsonify(command_center.panel(panel_id, last()))

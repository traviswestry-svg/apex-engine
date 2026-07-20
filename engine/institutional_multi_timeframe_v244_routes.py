"""HTTP routes for APEX 24.4 Multi-Timeframe Intelligence (read-only, advisory)."""
from flask import jsonify, request

from . import institutional_multi_timeframe_v244 as mtf

REQUIRED_ROUTES = (
    ("GET", "/api/multi-timeframe/status"),
    ("GET", "/api/multi-timeframe/alignment"),
    ("GET", "/api/multi-timeframe/conflicts"),
)


def verify_registered(app):
    present = {(m, str(rule)) for rule in app.url_map.iter_rules()
               for m in (rule.methods or set())}
    return [f"{m} {p}" for m, p in REQUIRED_ROUTES if (m, p) not in present]


def register_institutional_multi_timeframe_v244_routes(app, *, last_result_provider=None):
    def last():
        value = last_result_provider() if callable(last_result_provider) else {}
        return value if isinstance(value, dict) else {}

    @app.get('/api/multi-timeframe/status')
    def mtf_v244_status():
        return jsonify(mtf.status())

    @app.get('/api/multi-timeframe/alignment')
    def mtf_v244_alignment():
        return jsonify(mtf.alignment(last()))

    @app.get('/api/multi-timeframe/conflicts')
    def mtf_v244_conflicts():
        return jsonify(mtf.conflicts(last()))

    @app.get('/api/multi-timeframe/integration')
    def mtf_v244_integration():
        return jsonify(mtf.integration_signals(last()))

    @app.post('/api/multi-timeframe/alignment')
    def mtf_v244_alignment_adhoc():
        body = request.get_json(silent=True) or {}
        return jsonify(mtf.alignment(body))

    @app.post('/api/multi-timeframe/conflicts')
    def mtf_v244_conflicts_adhoc():
        body = request.get_json(silent=True) or {}
        return jsonify(mtf.conflicts(body))

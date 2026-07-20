"""HTTP routes for APEX 24.2 Institutional Replay & Simulator.

All routes are read-only / advisory. The canonical /api/replay/session route
dispatches by parameter so the legacy intraday session contract
(?ticker=&date=) continues to function while session_id addresses the new
immutable multi-engine replay.
"""
from flask import jsonify, request

from . import institutional_replay_v242 as replay

REQUIRED_ROUTES = (
    ("GET", "/api/replay/status"),
    ("GET", "/api/replay/session"),
    ("GET", "/api/replay/trade"),
    ("GET", "/api/replay/timeline"),
    ("POST", "/api/replay/simulator"),
)


def verify_registered(app):
    present = {(m, str(rule)) for rule in app.url_map.iter_rules()
               for m in (rule.methods or set())}
    return [f"{m} {p}" for m, p in REQUIRED_ROUTES if (m, p) not in present]


def register_institutional_replay_v242_routes(app, *, last_result_provider=None,
                                              legacy_session_provider=None):
    def last():
        value = last_result_provider() if callable(last_result_provider) else {}
        return value if isinstance(value, dict) else {}

    @app.get('/api/replay/status')
    def replay_v242_status():
        return jsonify(replay.status())

    @app.get('/api/replay/session')
    def replay_v242_session():
        session_id = request.args.get('session_id')
        if session_id:
            return jsonify(replay.session(session_id))
        # Backward compatible: legacy intraday session index (?ticker=&date=).
        if (request.args.get('date') or request.args.get('ticker')) and callable(legacy_session_provider):
            return legacy_session_provider()
        return jsonify(replay.list_sessions(int(request.args.get('limit', 100))))

    @app.post('/api/replay/capture')
    def replay_v242_capture():
        body = request.get_json(silent=True) or {}
        snapshot = body.get('last') if isinstance(body.get('last'), dict) else last()
        return jsonify(replay.capture(snapshot, session_key=body.get('session_key'),
                                      trade=body.get('trade'), actor=str(body.get('actor') or 'API')))

    @app.get('/api/replay/timeline')
    def replay_v242_timeline():
        session_id = request.args.get('session_id', '')
        return jsonify(replay.timeline(session_id))

    @app.get('/api/replay/trade')
    def replay_v242_trade():
        return jsonify(replay.trade(request.args.get('session_id'), request.args.get('decision_id')))

    @app.get('/api/replay/navigate')
    def replay_v242_navigate():
        return jsonify(replay.navigate(request.args.get('session_id', ''),
                                       action=request.args.get('action', 'PLAY'),
                                       cursor=int(request.args.get('cursor', 0)),
                                       timestamp=request.args.get('timestamp')))

    @app.post('/api/replay/simulator')
    def replay_v242_simulator():
        body = request.get_json(silent=True) or {}
        return jsonify(replay.simulate(str(body.get('session_id') or ''), body.get('scenario') or body))

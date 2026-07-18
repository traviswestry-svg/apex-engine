"""Routes and dashboard for APEX 11.1 Institutional Execution OS."""
from __future__ import annotations
from typing import Any, Callable, Mapping
from flask import jsonify, render_template
from .institutional_execution_os import VERSION, build_execution_snapshot, build_morning_readiness
from .operations_routes import _all_checks


def register_execution_os_routes(app, *, last_result_provider: Callable[[], Mapping[str, Any]]) -> None:
    def current():
        try:
            value = last_result_provider() or {}
            return value if isinstance(value, Mapping) else {}
        except Exception:
            return {}

    @app.get('/apex_os/execution')
    def execution_dashboard():
        return render_template('execution_os.html', version=VERSION)

    @app.get('/apex_os/readiness')
    def readiness_dashboard():
        return render_template('execution_os.html', version=VERSION, initial_tab='readiness')

    @app.get('/api/execution/score')
    @app.get('/api/execution/quality')
    @app.get('/api/execution/liquidity')
    @app.get('/api/execution/simulator')
    @app.get('/api/execution/fill-probability')
    @app.get('/api/execution/slippage')
    @app.get('/api/execution/position-quality')
    def execution_snapshot():
        return jsonify(build_execution_snapshot(current()))

    def readiness_payload():
        result = current()
        execution = build_execution_snapshot(result)
        checks = _all_checks(app)
        market_status = result.get('market_status') if isinstance(result.get('market_status'), Mapping) else {}
        market_open = bool(result.get('market_open', market_status.get('is_open', False)))
        return build_morning_readiness(system_checks=checks, execution=execution, market_open=market_open)

    @app.get('/api/readiness')
    @app.get('/api/readiness/details')
    @app.get('/api/readiness/checks')
    @app.get('/api/readiness/providers')
    @app.get('/api/readiness/report')
    def readiness():
        return jsonify(readiness_payload())

    @app.get('/api/readiness/history')
    def readiness_history():
        return jsonify({'ok': True, 'version': VERSION, 'status': 'COLLECTING', 'history': [], 'note': 'History starts after deployment; no values are fabricated.'})

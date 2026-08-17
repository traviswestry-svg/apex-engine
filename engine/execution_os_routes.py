"""Routes and dashboard for APEX 11.1 Institutional Execution OS."""
from __future__ import annotations
from .silent_degradation_observability import record_degradation
from typing import Any, Callable, Mapping
import threading
from flask import jsonify, render_template
from .institutional_execution_os import VERSION, build_execution_snapshot, build_morning_readiness
from .operations_routes import _all_checks


def register_execution_os_routes(
    app,
    *,
    last_result_provider: Callable[[], Mapping[str, Any]],
    session_provider: Callable[[], Any] | None = None,
    risk_config_provider: Callable[[], Mapping[str, Any]] | None = None,
) -> None:
    # APEX 50.7.2.1: initialize review/archive schemas off the request thread.
    # This guarantees evidence-audit visibility without adding startup latency.
    def _archive_schema_bootstrap():
        try:
            from .evening_archive_schema import init_evening_archive_db
            from .persistent_store import persistent_sqlite_path
            from .report_archive import init_db as init_readiness_archive
            recap_db = persistent_sqlite_path("APEX_GOVERNANCE_DB", "apex_governance.db")
            init_evening_archive_db(recap_db)
            init_readiness_archive()
        except Exception as exc:
            print(f"[APEX50.7.2.1] archive schema bootstrap failed (non-fatal): {exc}", flush=True)

    threading.Thread(target=_archive_schema_bootstrap, name="apex-archive-schema-bootstrap", daemon=True).start()
    def current():
        try:
            value = last_result_provider() or {}
            return value if isinstance(value, Mapping) else {}
        except Exception as exc:
            record_degradation(component="execution_os", operation="last_result_provider",
                               exc=exc, fallback="EMPTY_CURRENT_RESULT",
                               decision_authority_suppressed=True,
                               source="engine/execution_os_routes.py")
            return {}

    def current_session():
        if session_provider is None:
            return None
        try:
            return session_provider()
        except Exception as exc:
            record_degradation(component="execution_os", operation="session_provider",
                               exc=exc, fallback="UNKNOWN_SESSION",
                               decision_authority_suppressed=True,
                               source="engine/execution_os_routes.py")
            return None

    def current_risk_config():
        if risk_config_provider is None:
            return {}
        try:
            value = risk_config_provider() or {}
            return value if isinstance(value, Mapping) else {}
        except Exception as exc:
            record_degradation(component="execution_os", operation="risk_config_provider",
                               exc=exc, fallback="EMPTY_RISK_CONFIG",
                               decision_authority_suppressed=True,
                               source="engine/execution_os_routes.py")
            return {}

    @app.get('/apex_os/execution')
    def execution_dashboard():
        return render_template('execution_os.html', version=VERSION)

    @app.get('/apex_os/readiness')
    def readiness_dashboard():
        return render_template('execution_os.html', version=VERSION, initial_tab='readiness')

    @app.get('/apex_os/report-archive')
    def report_archive_dashboard():
        return render_template('report_archive.html', version=VERSION)

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
        session = current_session()
        # Prefer the canonical session detector for the open/closed decision so
        # readiness reflects the true session even when no scanner result exists
        # (e.g. weekends). Fall back to the last result's market flags otherwise.
        if isinstance(session, Mapping):
            session_market_open = str(session.get('session') or session.get('session_state') or '').upper() == 'MARKET_OPEN'
        elif isinstance(session, str):
            session_market_open = session.upper() == 'MARKET_OPEN'
        else:
            session_market_open = bool(result.get('market_open', market_status.get('is_open', False)))
        risk_cfg = current_risk_config()
        risk_config_ready = bool(risk_cfg.get('configured')) if 'configured' in risk_cfg else bool(risk_cfg)
        return build_morning_readiness(
            system_checks=checks,
            execution=execution,
            market_open=session_market_open,
            session=session,
            execution_checks=execution.get('checks'),
            risk_config_ready=risk_config_ready,
        )

    @app.get('/api/readiness')
    @app.get('/api/readiness/details')
    @app.get('/api/readiness/checks')
    @app.get('/api/readiness/providers')
    @app.get('/api/readiness/report')
    def readiness():
        payload = readiness_payload()
        try:
            from .report_archive import archive_readiness
            payload['report_archive'] = archive_readiness(payload)
        except Exception as exc:
            payload['report_archive'] = {'archived': False, 'error': f'{type(exc).__name__}: {exc}'}
        return jsonify(payload)

    @app.get('/api/readiness/history')
    def readiness_history():
        from .report_archive import readiness_history
        return jsonify(readiness_history())

    @app.get('/api/readiness/archive/<session_date>')
    def readiness_archive_detail(session_date):
        from .report_archive import get_readiness
        payload = get_readiness(session_date)
        if payload is None:
            return jsonify({'ok': False, 'status': 'NOT_FOUND', 'session_date': session_date}), 404
        return jsonify(payload)

    @app.get('/api/report-archive')
    def report_archive_catalog():
        from .report_archive import report_catalog
        return jsonify(report_catalog())

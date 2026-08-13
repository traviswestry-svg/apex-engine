"""Read-only APEX 10 dashboard evidence route."""
from flask import jsonify, request
from .dashboard_evidence import build_dashboard_evidence


def register_dashboard_evidence_routes(app, *, last_result_provider=None) -> None:
    @app.get('/api/apex10/evidence')
    def _apex10_evidence():
        ticker = (request.args.get('ticker') or 'SPX').upper()
        try:
            current = last_result_provider() if callable(last_result_provider) else {}
            return jsonify({'ok': True, 'evidence': build_dashboard_evidence(
                current_result=current, ticker=ticker)})
        except Exception as exc:
            return jsonify({'ok': True, 'evidence': {
                'available': False, 'ticker': ticker, 'reason': f'evidence recovered: {exc}',
                'guardrails': {'read_only': True}}})

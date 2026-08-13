"""HTTP routes for APEX 24.3 Strategy Research Laboratory.

All routes are offline research / advisory. The canonical /api/research/status
route merges the pre-existing research/similarity status (via
legacy_status_provider) so existing consumers keep their fields.
"""
from flask import jsonify, request

from . import institutional_research_lab_v243 as research

REQUIRED_ROUTES = (
    ("GET", "/api/research/status"),
    ("GET", "/api/research/strategies"),
    ("GET", "/api/research/experiments"),
    ("GET", "/api/research/performance"),
)


def verify_registered(app):
    present = {(m, str(rule)) for rule in app.url_map.iter_rules()
               for m in (rule.methods or set())}
    return [f"{m} {p}" for m, p in REQUIRED_ROUTES if (m, p) not in present]


def register_institutional_research_lab_v243_routes(app, *, legacy_status_provider=None):
    @app.get('/api/research/status')
    def research_v243_status():
        payload = {'ok': True}
        # Preserve pre-existing research/similarity status fields.
        if callable(legacy_status_provider):
            try:
                legacy = legacy_status_provider()
                if isinstance(legacy, dict):
                    payload.update(legacy)
            except Exception:
                pass
        payload.update(research.status())
        return jsonify(payload)

    @app.get('/api/research/strategies')
    def research_v243_strategies():
        return jsonify(research.strategies())

    @app.get('/api/research/performance')
    def research_v243_performance():
        return jsonify(research.performance())

    @app.get('/api/research/experiments')
    def research_v243_experiments():
        experiment_id = request.args.get('experiment_id')
        if experiment_id:
            return jsonify(research.experiment(experiment_id))
        return jsonify(research.experiments(int(request.args.get('limit', 100))))

    @app.post('/api/research/experiments')
    def research_v243_create_experiment():
        b = request.get_json(silent=True) or {}
        return jsonify(research.create_experiment(
            name=str(b.get('name') or ''), strategy=str(b.get('strategy') or ''),
            hypothesis=str(b.get('hypothesis') or ''), baseline_params=b.get('baseline_params'),
            notes=str(b.get('notes') or ''), actor=str(b.get('actor') or 'API')))

    @app.post('/api/research/experiments/revision')
    def research_v243_revise_experiment():
        b = request.get_json(silent=True) or {}
        return jsonify(research.add_revision(
            experiment_id=str(b.get('experiment_id') or ''), params=b.get('params') or {},
            notes=str(b.get('notes') or ''), before_metrics=b.get('before_metrics'),
            after_metrics=b.get('after_metrics'), actor=str(b.get('actor') or 'API')))

    @app.post('/api/research/analytics')
    def research_v243_analytics():
        b = request.get_json(silent=True) or {}
        return jsonify(research.performance_analytics(b.get('trades') or []))

    @app.get('/api/research/dashboard')
    def research_v243_dashboard():
        return jsonify(research.research_dashboard())

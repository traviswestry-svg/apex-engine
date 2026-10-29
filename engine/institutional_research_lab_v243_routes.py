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


    @app.get('/api/research/forecast-precision')
    def research_forecast_precision():
        """Read-only historical forecast precision and shadow evaluation."""
        from .morning_forecast_shadow_calibration import archived_precision_report
        try:
            limit = max(1, min(int(request.args.get('limit', 250)), 250))
            min_train = max(2, min(int(request.args.get('min_train', 20)), 120))
            window = max(min_train, min(int(request.args.get('window', 120)), 250))
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'INVALID_CALIBRATION_PARAMETERS'}), 400
        try:
            return jsonify(archived_precision_report(limit=limit,
                min_train=min_train, window=window))
        except Exception:
            app.logger.exception('Forecast precision archive unavailable')
            return jsonify({'ok': False, 'status': 'ARCHIVE_UNAVAILABLE',
                            'production_promotion': False}), 503

    @app.get('/api/research/regime-forecast-integrity')
    def research_regime_forecast_integrity():
        """Read-only archive-bound regime and reference-price integrity report."""
        from .regime_forecast_integrity import archived_report
        try:
            limit = max(1, min(int(request.args.get('limit', 250)), 250))
            exploratory_min_train = max(2, min(int(request.args.get('exploratory_min_train', 8)), 19))
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'INVALID_DIAGNOSTIC_PARAMETERS'}), 400
        try:
            return jsonify(archived_report(limit=limit, exploratory_min_train=exploratory_min_train))
        except Exception:
            app.logger.exception('Regime forecast archive unavailable')
            return jsonify({'ok': False, 'status': 'ARCHIVE_UNAVAILABLE',
                            'production_promotion': False}), 503

    @app.get('/api/research/regime-containment-provenance')
    def research_regime_containment_provenance():
        """Read-only morning vote/archive audit and containment shadow evaluation."""
        from .regime_containment_research import archived_report
        try:
            limit = max(1, min(int(request.args.get('limit', 250)), 250))
            min_train = max(2, min(int(request.args.get('min_train', 8)), 120))
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'INVALID_RESEARCH_PARAMETERS'}), 400
        try:
            return jsonify(archived_report(limit=limit, min_train=min_train))
        except Exception:
            app.logger.exception('Regime containment research unavailable')
            return jsonify({'ok': False, 'status': 'ARCHIVE_UNAVAILABLE',
                            'production_promotion': False}), 503

    @app.get('/api/research/regime-evidence-decorrelation')
    def research_regime_evidence_decorrelation():
        """Research-only family-aware regime and directional range comparison."""
        from .regime_evidence_decorrelation import archived_report
        try:
            limit = max(1, min(int(request.args.get('limit', 250)), 250))
            min_train = max(2, min(int(request.args.get('min_train', 8)), 120))
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'INVALID_RESEARCH_PARAMETERS'}), 400
        try:
            return jsonify(archived_report(limit=limit, min_train=min_train))
        except Exception:
            app.logger.exception('Regime evidence de-correlation research unavailable')
            return jsonify({'ok': False, 'status': 'ARCHIVE_UNAVAILABLE',
                            'production_promotion': False}), 503

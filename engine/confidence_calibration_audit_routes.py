"""Routes for APEX 66.8.0 Confidence Calibration Audit."""
from __future__ import annotations
from .confidence_calibration_audit import build_confidence_calibration_audit, health


def register_confidence_calibration_audit_routes(app):
    @app.get('/api/effectiveness/confidence-calibration')
    def apex_66_8_confidence_calibration_audit():
        from flask import jsonify, request
        try:
            return jsonify(build_confidence_calibration_audit(
                symbol=request.args.get('symbol', 'SPX'),
                minimum_sample=int(request.args.get('minimum_sample', 20)),
                limit=int(request.args.get('limit', 10000)),
            ))
        except (TypeError, ValueError) as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 400
        except Exception as exc:
            app.logger.exception('Confidence Calibration Audit failed')
            return jsonify({'ok': False, 'status': 'ERROR', 'error': type(exc).__name__}), 500

    @app.get('/api/effectiveness/confidence-calibration/health')
    def apex_66_8_confidence_calibration_health():
        from flask import jsonify, request
        try:
            return jsonify(health(symbol=request.args.get('symbol', 'SPX')))
        except Exception as exc:
            app.logger.exception('Confidence Calibration Audit health failed')
            return jsonify({'ok': False, 'status': 'ERROR', 'error': type(exc).__name__}), 500

    @app.get('/apex_os/confidence-calibration')
    def apex_66_8_confidence_calibration_dashboard():
        from flask import render_template
        return render_template('confidence_calibration_audit.html')

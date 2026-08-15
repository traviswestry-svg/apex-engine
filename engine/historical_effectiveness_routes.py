"""Routes for APEX 66.7.0 Historical Effectiveness Observatory."""
from __future__ import annotations
from .historical_effectiveness_observatory import build_observatory, health


def register_historical_effectiveness_routes(app):
    @app.get('/api/effectiveness/observatory')
    def apex_66_7_effectiveness_observatory():
        from flask import jsonify, request
        try:
            payload = build_observatory(
                symbol=request.args.get('symbol', 'SPX'),
                minimum_sample=int(request.args.get('minimum_sample', 20)),
                limit=int(request.args.get('limit', 10000)),
            )
            return jsonify(payload)
        except (TypeError, ValueError) as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 400
        except Exception as exc:
            app.logger.exception('Historical Effectiveness Observatory failed')
            return jsonify({'ok': False, 'status': 'ERROR', 'error': type(exc).__name__}), 500

    @app.get('/api/effectiveness/health')
    def apex_66_7_effectiveness_health():
        from flask import jsonify, request
        try:
            return jsonify(health(symbol=request.args.get('symbol', 'SPX')))
        except Exception as exc:
            app.logger.exception('Historical Effectiveness health failed')
            return jsonify({'ok': False, 'status': 'ERROR', 'error': type(exc).__name__}), 500

    @app.get('/apex_os/effectiveness')
    def apex_66_7_effectiveness_dashboard():
        from flask import render_template
        return render_template('historical_effectiveness.html')

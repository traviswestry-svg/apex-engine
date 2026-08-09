"""APEX 11.2/11.3 APIs and dashboard routes."""
from __future__ import annotations
from flask import jsonify, render_template, request
from .institutional_narrative import VERSION as NARRATIVE_VERSION, build_institutional_narrative, build_consensus_gauge, build_conviction
from .institutional_decision_object import build_canonical_institutional_decision
from .decision_review import VERSION as REVIEW_VERSION, build_decision_review, build_replay, record_decision_snapshot
from . import recommendation_ledger as ledger


def register_institutional_intelligence_routes(app, *, last_result_provider):
    def current():
        value = last_result_provider() or {}
        return value if isinstance(value, dict) else {}

    @app.get('/api/institutional-narrative')
    def narrative(): return jsonify({'ok': True, **build_institutional_narrative(current(), session_state=request.args.get('session'))})

    @app.get('/api/institutional-consensus')
    def consensus(): return jsonify({'ok': True, 'version': NARRATIVE_VERSION, **build_consensus_gauge(current())})

    @app.get('/api/institutional-conviction')
    def conviction(): return jsonify({'ok': True, 'version': NARRATIVE_VERSION, **build_conviction(current())})

    @app.get('/api/institutional-decision')
    def decision(): return jsonify({'ok': True, **build_canonical_institutional_decision(current(), recommendation_id=request.args.get('recommendation_id'), session_state=request.args.get('session'))})

    @app.get('/api/institutional-thesis')
    def institutional_thesis():
        obj = build_canonical_institutional_decision(current(), recommendation_id=request.args.get('recommendation_id'), session_state=request.args.get('session'))
        return jsonify({'ok': True, 'version': obj.get('engine_version'), 'ticker': obj.get('ticker'), 'timestamp': obj.get('timestamp'), 'thesis': obj.get('thesis') or {}, 'lifecycle': obj.get('thesis_lifecycle') or {}, 'events': obj.get('thesis_evolution_timeline') or []})

    @app.get('/api/institutional-thesis/history')
    def institutional_thesis_history():
        from .thesis_lifecycle import get_state, get_events
        ticker = str(request.args.get('ticker') or 'SPX').upper()
        session_date = str(request.args.get('session_date') or '').strip()
        if not session_date:
            return jsonify({'ok': False, 'error': 'session_date is required', 'expected': 'YYYY-MM-DD'}), 400
        row = get_state(ticker, session_date)
        if row is None:
            return jsonify({'ok': False, 'error': 'not_found', 'ticker': ticker, 'session_date': session_date}), 404
        return jsonify({'ok': True, 'ticker': ticker, 'session_date': session_date, 'thesis': row, 'events': get_events(row['thesis_id'])})

    @app.get('/api/decision-review/<recommendation_id>')
    def review(recommendation_id):
        payload = build_decision_review(recommendation_id)
        return (jsonify({'ok': False, 'error': 'not_found'}), 404) if payload is None else jsonify({'ok': True, **payload})

    @app.get('/api/decision-replay/<recommendation_id>')
    def replay(recommendation_id):
        payload = build_replay(recommendation_id)
        return (jsonify({'ok': False, 'error': 'not_found'}), 404) if payload is None else jsonify({'ok': True, **payload})

    @app.post('/api/decision-review/<recommendation_id>/snapshot')
    def snapshot(recommendation_id):
        try: return jsonify({'ok': True, 'version': REVIEW_VERSION, **record_decision_snapshot(recommendation_id, current())}), 201
        except KeyError: return jsonify({'ok': False, 'error': 'not_found'}), 404

    @app.get('/api/recommendation-evolution/<recommendation_id>')
    def evolution(recommendation_id):
        row = ledger.get_recommendation(recommendation_id)
        if row is None: return jsonify({'ok': False, 'error': 'not_found'}), 404
        return jsonify({'ok': True, 'recommendation_id': recommendation_id, 'events': row.get('events', []), 'empty': not bool(row.get('events'))})

    @app.get('/apex_os/institutional_intelligence')
    def institutional_intelligence_dashboard(): return render_template('institutional_intelligence.html')

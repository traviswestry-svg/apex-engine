"""Read/proposal routes for Sprint 5 learning. Promotion is explicit POST only."""
from flask import jsonify, request
from . import feature_store_db
from .learning_calibration import (LEARNING_VERSION, active_policy, apply_active_calibration,
    build_policy_proposal, calibration_report, init_learning_db, persist_proposal, promote_policy,
    outcome_to_binary)


def register_learning_routes(app) -> None:
    if not feature_store_db.is_ready():
        feature_store_db.init_db()
    init_learning_db()

    @app.get('/api/learning/calibration')
    def _calibration():
        sessions = feature_store_db.sessions('features')
        if len(sessions) < 2:
            return jsonify({'ok': True, 'version': LEARNING_VERSION, 'available': False,
                            'reason': 'at least two settled sessions are required'})
        cut = max(1, int(len(sessions) * 0.8))
        if cut >= len(sessions): cut = len(sessions) - 1
        pairs = feature_store_db.load_training_pairs(train_sessions=sessions[:cut], eval_sessions=sessions[cut:])
        return jsonify({'ok': True, 'version': LEARNING_VERSION,
                        'train': calibration_report(pairs['train']),
                        'evaluation': calibration_report(pairs['eval']),
                        'active_policy': active_policy()})

    @app.post('/api/learning/proposals')
    def _proposal():
        body = request.get_json(silent=True) or {}
        train = body.get('train_sessions') or []
        evaluate = body.get('eval_sessions') or []
        proposal = build_policy_proposal(train_sessions=train, eval_sessions=evaluate)
        proposal['persisted'] = persist_proposal(proposal)
        return jsonify({'ok': True, 'proposal': proposal})

    @app.post('/api/learning/policies/<policy_id>/promote')
    def _promote(policy_id):
        body = request.get_json(silent=True) or {}
        result = promote_policy(policy_id, str(body.get('note') or ''))
        return jsonify(result), (200 if result.get('ok') else 409)

    @app.get('/api/learning/outcomes/<sample_id>')
    def _outcome(sample_id):
        sample = feature_store_db.get_sample(sample_id)
        if not sample:
            return jsonify({'ok': True, 'available': False, 'sample_id': sample_id, 'reason': 'sample not found'})
        labels = ((sample.get('post_outcome') or {}).get('labels') or {})
        binary = outcome_to_binary(labels)
        return jsonify({'ok': True, 'available': bool(labels), 'sample_id': sample_id,
                        'final_outcome': labels.get('final_outcome'),
                        'calibration_target': binary,
                        'ambiguous_for_binary_calibration': bool(labels) and binary is None})

    @app.get('/api/learning/apply')
    def _apply():
        return jsonify({'ok': True, 'calibration': apply_active_calibration(request.args.get('confidence'))})

import os
import pytest
from engine import feature_store_db
from engine.feature_store import Feature, build_pre_decision_vector, build_label_record, LeakageError
from engine.learning_calibration import (apply_active_calibration, build_policy_proposal,
    calibration_report, outcome_to_binary, persist_proposal, promote_policy)

@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    path=str(tmp_path/'learn.db')
    monkeypatch.setattr(feature_store_db, '_DB_PATH', path)
    monkeypatch.setattr('engine.learning_calibration._DB_PATH', path)
    feature_store_db._DB_READY=False
    assert feature_store_db.init_db()
    yield


def _write(day, idx, conf, outcome):
    dec=f'{day}T10:{idx%60:02d}:00+00:00'
    sid=f'{day}-{idx}'
    v=build_pre_decision_vector(sample_id=sid, decision_time=dec, ticker='SPX',
        session_date=day, features=[Feature('ici', conf, dec, 'test')])
    assert feature_store_db.write_features(v)
    lab=build_label_record(sample_id=sid, decision_time=dec,
        settled_at=f'{day}T16:00:00+00:00', session_date=day,
        labels={'final_outcome': outcome}, label_basis='test')
    assert feature_store_db.write_label(lab)


def test_outcome_mapping_excludes_ambiguous():
    assert outcome_to_binary({'final_outcome':'TARGET_ONLY'}) == 1
    assert outcome_to_binary({'final_outcome':'STOP_FIRST'}) == 0
    assert outcome_to_binary({'final_outcome':'NEITHER'}) is None


def test_calibration_report():
    rows=[{'features':{'ici':80},'labels':{'final_outcome':'TARGET_ONLY'}},
          {'features':{'ici':80},'labels':{'final_outcome':'STOP_ONLY'}}]
    out=calibration_report(rows)
    assert out['sample_count']==2 and out['brier_score'] is not None


def test_proposal_is_chronological_and_not_auto_active():
    for i in range(60): _write('2026-07-10', i, 90, 'TARGET_ONLY' if i<30 else 'STOP_ONLY')
    for i in range(60): _write('2026-07-11', i, 90, 'TARGET_ONLY' if i<30 else 'STOP_ONLY')
    for i in range(50): _write('2026-07-12', i, 90, 'TARGET_ONLY' if i<25 else 'STOP_ONLY')
    p=build_policy_proposal(train_sessions=['2026-07-10','2026-07-11'], eval_sessions=['2026-07-12'])
    assert p['sample_counts']=={'train':120,'eval':50}
    assert p['guardrails']['automatic_activation'] is False
    assert abs(p['parameters']['slope']-1.0) <= 0.100001
    assert persist_proposal(p)
    result=promote_policy(p['policy_id'])
    if p['guardrails']['promotion_eligible']:
        assert result['ok']
    else:
        assert not result['ok']


def test_overlap_rejected():
    with pytest.raises(LeakageError):
        build_policy_proposal(train_sessions=['2026-07-10'], eval_sessions=['2026-07-10'])


def test_no_policy_is_identity():
    out=apply_active_calibration(77)
    assert out['calibrated_confidence']==77 and out['policy_applied'] is False

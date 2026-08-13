import os
import tempfile

from engine import feature_store_db as db
from engine.feature_store import build_label_record
from engine.historical_similarity import find_similar, find_similar_to_sample


def _vector(sid, day, gamma='LONG_GAMMA', aggression=80):
    return {"sample_id": sid, "session_date": day, "ticker": "SPX",
            "decision_time": f"{day}T10:00:00", "features": {
                "gamma_regime": gamma, "auction_state": "BALANCED",
                "cluster_directional_interpretation": "BULLISH",
                "cluster_aggression_score": aggression,
                "cluster_repeat_intensity_score": 70,
                "cluster_total_premium": 500000,
            }, "feature_availability": {}, "feature_count": 6,
            "max_feature_lag_seconds": 0, "schema_version": "test"}


def setup_function(_):
    fd, path = tempfile.mkstemp(suffix='.db'); os.close(fd)
    db._DB_PATH = path; db._DB_READY = False; db.init_db()


def teardown_function(_):
    path=db._DB_PATH; db._DB_READY=False
    try: os.unlink(path)
    except OSError: pass


def _seed(sid, day, gamma='LONG_GAMMA', aggression=80, settled=None, outcome='TARGET_FIRST'):
    v=_vector(sid, day, gamma, aggression); assert db.write_features(v)
    rec=build_label_record(sample_id=sid, decision_time=v['decision_time'],
        settled_at=settled or f'{day}T16:00:00', session_date=day,
        labels={'final_outcome': outcome}, label_basis='test')
    assert db.write_label(rec)


def test_similarity_prefers_closest_and_explains_factors():
    _seed('a','2026-07-10', aggression=79)
    _seed('b','2026-07-11', gamma='SHORT_GAMMA', aggression=20, outcome='STOP_FIRST')
    out=find_similar(query_features=_vector('q','2026-07-15')['features'],
                     decision_time='2026-07-15T10:00:00', top_k=2)
    assert out['matches'][0]['sample_id']=='a'
    assert out['matches'][0]['top_differences']
    assert out['guardrails']['outcomes_used_in_distance'] is False


def test_future_or_unsettled_labels_are_excluded():
    _seed('past','2026-07-10')
    _seed('late','2026-07-11', settled='2026-07-20T16:00:00')
    out=find_similar(query_features=_vector('q','2026-07-15')['features'],
                     decision_time='2026-07-15T10:00:00')
    ids={m['sample_id'] for m in out['matches']}
    assert 'past' in ids and 'late' not in ids


def test_same_session_is_excluded_by_default():
    _seed('old','2026-07-10')
    _seed('same','2026-07-15', settled='2026-07-15T11:00:00')
    out=find_similar(query_features=_vector('q','2026-07-15')['features'],
                     decision_time='2026-07-15T12:00:00')
    assert 'same' not in {m['sample_id'] for m in out['matches']}


def test_rate_is_withheld_for_thin_neighbourhood():
    _seed('a','2026-07-10')
    out=find_similar(query_features=_vector('q','2026-07-15')['features'],
                     decision_time='2026-07-15T10:00:00')
    assert out['outcome_evidence']['edge_claim_permitted'] is False
    assert out['outcome_evidence']['target_first_interval'] is None


def test_sample_lookup_uses_frozen_query_vector():
    _seed('a','2026-07-10')
    q=_vector('q','2026-07-15'); assert db.write_features(q)
    out=find_similar_to_sample('q')
    assert out['available'] is True
    assert out['matches'][0]['sample_id']=='a'

import json
import sqlite3
import pytest
from engine import institutional_evidence as ev
from engine import institutional_similarity as sim

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, 'DB_PATH', str(tmp_path/'evidence.db'))
    monkeypatch.setattr(sim, 'DB_PATH', str(tmp_path/'similarity.db'))
    ev.init_db(); sim.init_db()


def seed(rid, observed_at, *, regime='TREND', direction='BULLISH', confidence=80):
    package={
        'captured_at': observed_at,
        'canonical_decision': {
            'recommendation_id': rid, 'timestamp': observed_at, 'strategy': 'CALL_DEBIT',
            'direction': direction, 'market_state': regime, 'market_regime': regime,
            'confidence': confidence,
            'institutional_consensus': {'dominant_direction': direction, 'agreement_percentage': 80, 'consensus_grade': 'A'},
            'conviction': {'conviction_score': 78, 'conviction_grade': 'HIGH'},
            'execution': {'execution_score': 85, 'trading_mode': 'FULLY_OPERATIONAL'},
            'position_quality': {'position_quality_score': 82},
            'liquidity': {'grade': 'A'},
            'evidence': {'auction': {'state': 'OPENING_DRIVE', 'value_relationship': 'ABOVE_VALUE'}, 'gamma': {'regime': 'SHORT_GAMMA'}, 'flow': {'bias': direction}}
        },
        'snapshots': {}, 'provenance': {'build': 'test'}, 'schema_version': 'v1', 'versions': {'build':'test'}, 'build_version':'test', 'immutable': True
    }
    with sqlite3.connect(ev.DB_PATH) as c:
        c.execute("INSERT INTO evidence_packages VALUES(?,?,?,?,?,?,?,?,?)",(f'p-{rid}',rid,observed_at,'v1','test','READY',json.dumps(package),f'h-{rid}',None))


def test_feature_vector_is_versioned_deterministic_and_immutable(isolated):
    seed('r1','2026-07-01T14:00:00+00:00')
    a=sim.create_vector('r1'); b=sim.create_vector('r1')
    assert a['created'] is True and b['created'] is False
    assert a['feature_version']==sim.FEATURE_VERSION
    assert a['feature_hash']==b['feature_hash']
    assert b['immutable'] is True


def test_similarity_prefers_matching_context_and_blocks_future(isolated):
    seed('old-close','2026-07-01T14:00:00+00:00',regime='TREND',direction='BULLISH',confidence=78)
    seed('old-far','2026-07-02T14:00:00+00:00',regime='BALANCE',direction='BEARISH',confidence=45)
    seed('base','2026-07-03T14:00:00+00:00',regime='TREND',direction='BULLISH',confidence=80)
    seed('future','2026-07-04T14:00:00+00:00',regime='TREND',direction='BULLISH',confidence=80)
    for rid in ('old-close','old-far','base','future'): sim.create_vector(rid)
    out=sim.search('base',top_k=10)
    ids=[m['recommendation_id'] for m in out['matches']]
    assert ids[0]=='old-close'
    assert 'future' not in ids
    assert out['look_ahead_guard']=='ENFORCED'
    assert out['outcome_analytics_status']=='INSUFFICIENT_HISTORY'


def test_schema_and_empty_status(isolated):
    assert sim.status()['status']=='COLLECTING'
    s=sim.schema()
    assert s['feature_version']==sim.FEATURE_VERSION
    assert 'market_regime' in s['features']


def test_missing_evidence_fails_closed(isolated):
    out=sim.create_vector('missing')
    assert out['status']=='UNAVAILABLE' and out['ok'] is False


def test_routes_and_dashboard(isolated):
    seed('r1','2026-07-01T14:00:00+00:00')
    import app as apex_app
    c=apex_app.app.test_client()
    assert c.post('/api/research/vector/r1').status_code in (200,201)
    for path in ['/api/research/vector/r1','/api/research/schema','/api/research/features','/api/research/institutional-status','/api/research/institutional-similarity/r1','/apex_os/institutional_similarity']:
        assert c.get(path).status_code==200,path

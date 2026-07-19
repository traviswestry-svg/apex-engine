import pytest
from engine.institutional_learning_engine import LearningStore
from engine.strategy_discovery_engine import StrategyDiscoveryStore, build_strategy_discovery, match_current_market


def seed(db, n=24):
    learning=LearningStore(str(db))
    for i in range(n):
        learning.record('SPX','BULL_PUT',{'premium_regime':'GAMMA_PIN','direction':'BULLISH','auction_state':'BALANCED','gamma_regime':'POSITIVE','vix_regime':'LOW','time_bucket':'MORNING'},outcome='LOSS' if i % 6 == 5 else 'WIN',pnl=-160 if i % 6 == 5 else 120)


def test_discover_promote_playbook_and_similarity(tmp_path):
    db=tmp_path/'d.db'; seed(db)
    store=StrategyDiscoveryStore(str(db))
    run=store.discover(min_sample=20)
    assert run['readiness']=='READY'
    p=run['best_pattern']; assert p['metrics']['expected_value']>0
    promoted=store.promote(p['pattern_id'],'tester'); assert promoted['promoted']
    book=store.playbook(); assert book['active_pattern_count']==1
    match=match_current_market(store,{'ticker':'SPX','premium_regime':'GAMMA_PIN','direction':'BULLISH','auction_state':'BALANCED','gamma_regime':'POSITIVE','vix_regime':'LOW','time_bucket':'MORNING'})
    assert match['closest_pattern']['similarity_score']==1.0
    built=build_strategy_discovery(store,{'ticker':'SPX','premium_regime':'GAMMA_PIN','direction':'BULLISH'})
    assert built['institutional_playbook']['active_pattern_count']==1


def test_developing_pattern_cannot_promote(tmp_path):
    db=tmp_path/'d.db'; seed(db,6)
    store=StrategyDiscoveryStore(str(db)); run=store.discover(min_sample=20)
    with pytest.raises(ValueError): store.promote(run['best_pattern']['pattern_id'])


def test_retire_preserves_audit(tmp_path):
    db=tmp_path/'d.db'; seed(db)
    store=StrategyDiscoveryStore(str(db)); p=store.discover(min_sample=20)['best_pattern']
    store.promote(p['pattern_id']); result=store.retire(p['pattern_id'],reason='drift')
    assert result['status']=='RETIRED'; assert len(store.audit())==2

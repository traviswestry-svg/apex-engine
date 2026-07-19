from engine.institutional_learning_engine import LearningStore, build_learning_intelligence

def test_learning_records_and_analyzes(tmp_path):
    s=LearningStore(str(tmp_path/'l.db'))
    for i in range(6):
        s.record('SPX','BULL_PUT',{'premium_regime':'GAMMA_PIN','direction':'BULLISH','vix_regime':'LOW'},outcome='WIN' if i<5 else 'LOSS',pnl=100 if i<5 else -150)
    r=build_learning_intelligence(s,{'ticker':'SPX','premium_regime':'GAMMA_PIN','direction':'BULLISH','vix_regime':'LOW'},min_sample=5)
    assert r['readiness']=='READY'
    assert r['best_pattern']['strategy']=='BULL_PUT'
    assert r['similar_patterns']

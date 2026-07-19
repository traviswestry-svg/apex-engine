from engine.trade_lifecycle_intelligence import LifecycleStore, evaluate_trade_lifecycle

def test_lifecycle_exits_on_breach(tmp_path):
    r=evaluate_trade_lifecycle({'position_id':'p1','entry_credit':2,'current_debit':4,'max_loss':800,'contracts':1},{'short_strike_breached':True,'minutes_to_close':100})
    assert r['action']=='EXIT'
    s=LifecycleStore(str(tmp_path/'x.db')); rec=s.record('p1',r)
    assert rec['id'] and s.recent(1)[0]['action']=='EXIT'

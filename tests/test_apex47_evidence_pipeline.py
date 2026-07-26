from datetime import datetime, timedelta, timezone
from engine.canonical_decision import build_snapshot
from engine.evidence_pipeline import record_snapshot, record_price, readiness
from engine.outcome_grader import run_grader
from engine.release_manifest import manifest

def test_manifest_is_canonical_47():
    m=manifest(); assert m['apex_version']=='47.0.6'; assert m['canonical_app']=='app.py'; assert 'evidence_readiness' in m['active_capabilities']

def test_snapshot_contract_actionable():
    s=build_snapshot({'timestamp':'2026-07-27T14:00:00+00:00','session':'RTH','price':7000,'direction':'BULLISH','action':'ENTER','confidence':88},'SPX')
    assert s['learning_eligible'] is True; assert s['execution_authorized'] is False; assert s['decision_id']

def test_non_actionable_is_explicitly_excluded(tmp_path):
    db=tmp_path/'e.db'; old=(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat()
    s=build_snapshot({'timestamp':old,'session':'CLOSED','price':7000,'direction':'NEUTRAL','action':'STAND_DOWN'},'SPX')
    record_snapshot(s,db); out=run_grader(db,horizon_seconds=60)
    assert out['excluded']==1; assert out['readiness']['exclusion_reasons']['NON_ACTIONABLE']==1

def test_actionable_grades_from_forward_price(tmp_path):
    db=tmp_path/'g.db'; start=datetime.now(timezone.utc)-timedelta(minutes=10)
    s=build_snapshot({'timestamp':start.isoformat(),'session':'RTH','price':7000,'direction':'BULLISH','action':'ENTER','confidence':80},'SPX')
    record_snapshot(s,db); record_price('SPX',7000,start.isoformat(),db); record_price('SPX',7005,(start+timedelta(seconds=60)).isoformat(),db)
    out=run_grader(db,horizon_seconds=60); assert out['graded']==1; assert readiness(db)['graded_outcomes']==1

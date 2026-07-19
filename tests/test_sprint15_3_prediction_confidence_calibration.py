import importlib
from pathlib import Path
from engine import prediction_confidence_calibration as pcce

def setup_db(tmp_path,monkeypatch):
    from engine import institutional_governance as gov
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'t.db')); importlib.reload(pcce); pcce.init_db()

def test_ingest_is_immutable(tmp_path,monkeypatch):
    setup_db(tmp_path,monkeypatch); a=pcce.ingest('p1',80,True); b=pcce.ingest('p1',10,False)
    assert a['created'] and b['status']=='IMMUTABLE_EXISTS' and float(b['confidence'])==80

def test_metrics_are_deterministic(tmp_path,monkeypatch):
    setup_db(tmp_path,monkeypatch)
    for i,(p,y) in enumerate([(90,1),(80,1),(70,0),(60,1),(40,0)]): pcce.ingest(str(i),p,y)
    a=pcce.analyze(); b=pcce.analyze(); assert a['metrics']==b['metrics'] and a['reliability_bins']==b['reliability_bins']

def test_brier_score_correct(tmp_path,monkeypatch):
    setup_db(tmp_path,monkeypatch); pcce.ingest('a',100,True); pcce.ingest('b',0,False)
    assert pcce.analyze()['metrics']['brier_score']==0

def test_persisted_analysis_is_hashed(tmp_path,monkeypatch):
    setup_db(tmp_path,monkeypatch); pcce.ingest('a',75,True); x=pcce.analyze(persist=True)
    assert x['created'] and len(x['integrity_hash'])==64 and pcce.analyses()[0]['analysis_id']==x['analysis_id']

def test_safety_contract(tmp_path,monkeypatch):
    setup_db(tmp_path,monkeypatch); s=pcce.status(); assert not s['production_confidence_mutation_enabled'] and not s['automatic_promotion_enabled'] and s['production_effect']=='NONE'

def test_routes_and_dashboard_exist():
    root=Path(__file__).parents[1]; routes=(root/'engine/institutional_roadmap_routes.py').read_text(); html=(root/'templates/prediction_confidence_calibration.html').read_text()
    assert '/api/calibration/status' in routes and '/api/calibration/analyze' in routes and '/apex_os/confidence_calibration' in routes and 'Reliability Curve' in html

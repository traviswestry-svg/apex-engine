import importlib

def test_readiness_archive_and_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_GOVERNANCE_DB', str(tmp_path/'gov.db'))
    import engine.report_archive as ra
    ra = importlib.reload(ra)
    p={'score':92,'trading_mode':'PREMARKET','session_date':'2026-08-03','recommendation':'READY'}
    a=ra.archive_readiness(p); assert a['archived'] and a['saved'] and a['is_official']
    b=ra.archive_readiness(p); assert b['archived'] and not b['saved']
    p2={**p,'score':95}; c=ra.archive_readiness(p2); assert c['saved'] and not c['is_official']
    h=ra.readiness_history(); assert h['count']==1 and h['items'][0]['revision_count']==2
    d=ra.get_readiness('2026-08-03'); assert d['score']==92 and d['archive']['is_official']
    cat=ra.report_catalog(); assert cat['items'][0]['morning_readiness'] is True

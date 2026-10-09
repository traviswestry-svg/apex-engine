import json, sqlite3
from engine.open_discovery_forward_validation import capture_forward, ensure_schema, _extract_structural

def _snap(**kw):
    x={'ticker':'SPX','direction':'BULLISH','action':'NO_TRADE','entry_reference':6700.0,'confidence':75.0,
       'learning_eligible':False,'range_intelligence':{'range_intelligence':{'unified_structural_map':{'available':True,'regime_pivot':{'price':6701},'reversal_path':{'state':'REVERSAL_DEVELOPING'}}}}}
    x.update(kw); return x

def test_capture_only_rth_open_discovery_and_first_is_candidate():
    c=sqlite3.connect(':memory:'); c.row_factory=sqlite3.Row
    assert capture_forward(c,'d1','2026-10-02T13:35:00+00:00',_snap())
    assert capture_forward(c,'d2','2026-10-02T13:36:00+00:00',_snap())
    rows=c.execute('select * from open_discovery_shadow_forward order by captured_at').fetchall()
    assert rows[0]['persistence_ordinal']==1 and rows[0]['shadow_status']=='SHADOW_ELIGIBLE_CANDIDATE'
    assert rows[1]['persistence_ordinal']==2 and rows[1]['shadow_status']=='SHADOW_CONTROL_PERSISTENT'
    assert not capture_forward(c,'weekend','2026-10-04T13:35:00+00:00',_snap())

def test_structural_capture_is_exact_and_not_reconstructed():
    e=_extract_structural(_snap())
    assert e['structural_fields_available'] is True and e['reconstructed'] is False
    assert any('unified_structural_map' in p for p in e['field_paths'])
    assert any(v.get('regime_pivot',{}).get('price')==6701 for p,v in e['fields'].items() if p.endswith('unified_structural_map'))

def test_no_candidate_for_actionable_decision():
    c=sqlite3.connect(':memory:'); c.row_factory=sqlite3.Row
    assert not capture_forward(c,'a','2026-10-02T13:35:00+00:00',_snap(action='TRADE',learning_eligible=True))

def test_release_metadata_69_10_34():
    m=json.load(open('config/apex_release_manifest.json'))
    assert m['apex_version']==m['semantic_version']==m['application_version']=='69.10.36'
    reg=open('config/apex_capability_registry.yaml').read()
    assert 'apex_version: 69.10.37' in reg
    assert 'open_discovery_shadow_candidate_forward_validation:' in reg

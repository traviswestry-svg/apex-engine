from engine.open_discovery_shadow_eligibility import _cluster_rows, _chronological_split, _discover

def _r(ts,missed,conf=75,direction='BULLISH',state='NO_TRADE'):
    return {'decision_id':ts,'captured_at':ts,'ticker':'SPX','direction':direction,'confidence':conf,'horizon_seconds':300,
            'missed_opportunity':missed,'protective_abstention':not missed,
            'classification':'MISSED_OPPORTUNITY' if missed else 'PROTECTIVE_ABSTENTION',
            'causality':{'families':{'DECISION_AUTHORITY':{'contributor_states':{state:1}}}}}

def test_cluster_projection_has_decision_time_fields_only():
    cs=_cluster_rows([_r('2026-09-21T13:31:00+00:00',True)])
    assert cs[0]['confidence_bucket']=='70_79'
    assert 'mfe' not in cs[0] and 'mae' not in cs[0] and 'directional_move' not in cs[0]

def test_chronological_split_is_session_date_disjoint():
    rows=[]
    for day in range(21,27): rows.append(_r(f'2026-09-{day:02d}T13:31:00+00:00',day%2==0))
    cs=_cluster_rows(rows); tr,ho,meta=_chronological_split(cs)
    assert meta['status']=='READY'
    assert {x['session_date_et'] for x in tr}.isdisjoint({x['session_date_et'] for x in ho})

def test_candidate_requires_holdout_support_and_lift():
    train=[]; hold=[]
    for i in range(8):
        train.append({'classification':'MISSED_OPPORTUNITY' if i<4 else 'PROTECTIVE_ABSTENTION','direction':'BULLISH','confidence_bucket':'GE90','confidence_trajectory':'STABLE','persistence_bucket':'ONE','family_signature':'A','state_signature':'A:X'})
    for i in range(4):
        hold.append({'classification':'MISSED_OPPORTUNITY' if i<2 else 'PROTECTIVE_ABSTENTION','direction':'BULLISH','confidence_bucket':'GE90','confidence_trajectory':'STABLE','persistence_bucket':'ONE','family_signature':'A','state_signature':'A:X'})
    # Equal-to-baseline cohorts are not promoted merely because they have support.
    assert not any(x['chronological_validation_pass'] for x in _discover(train,hold))

def test_release_metadata_69_10_33():
    import json
    m=json.load(open('config/apex_release_manifest.json'))
    assert m['apex_version']==m['semantic_version']==m['application_version']=='69.10.35'
    reg=open('config/apex_capability_registry.yaml').read()
    assert 'apex_version: 69.10.35' in reg
    assert 'open_discovery_counterfactual_discrimination_shadow_eligibility:' in reg

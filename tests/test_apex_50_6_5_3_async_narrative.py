import os, time

def test_async_job_persists_and_completes(tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_ASYNC_NARRATIVE_DB', str(tmp_path/'jobs.db'))
    from engine import async_narrative as an
    from engine import morning_brief as mb
    monkeypatch.setattr(mb, 'call_anthropic', lambda prompt, **kw: ('## SECTION 1 — EXECUTIVE SUMMARY\nAsync works.', None, {'outcome':'SUCCESS','attempts':[{'attempt':1}], 'network_call_count':1, 'total_duration_ms':12.3, 'circuit':{'state':'CLOSED'}}))
    key=an.job_key('2026-08-03','NEXT_SESSION_PREP')
    j=an.schedule(key=key,prompt='x',api_key='k',model='m',target_session_date='2026-08-03',brief_mode='NEXT_SESSION_PREP',force=True)
    assert j['status'] in {'PENDING','RUNNING','COMPLETE'}
    deadline=time.time()+2
    while time.time()<deadline:
        j=an.get_job(key)
        if j and j['status']=='COMPLETE': break
        time.sleep(.02)
    assert j['status']=='COMPLETE'
    assert 'Async works' in j['narrative']
    assert j['attempt_count']==1

def test_generate_brief_async_does_not_call_llm_inline(monkeypatch):
    from engine import morning_brief as mb
    scheduled={}
    monkeypatch.setenv('ANTHROPIC_API_KEY','k')
    import engine.async_narrative as an
    monkeypatch.setattr(an,'get_job',lambda key: None)
    def fake_schedule(**kw): scheduled.update(kw); return {'status':'PENDING','version':an.VERSION}
    monkeypatch.setattr(an,'schedule',fake_schedule)
    called={'n':0}
    def inline(*a,**k): called['n']+=1; raise AssertionError('LLM must not run inline')
    monkeypatch.setattr(mb,'build_deterministic',lambda **kw: (type('D',(),{'to_dict':lambda self:{'spot':7489.52,'levels':[],'trade_map':[],'expected_move':{},'gamma_regime':'unknown'}})(), 'SECTIONS', {'spot':7489.52}))
    out=mb.generate_morning_brief(cache={},narrative_cache={},session_context={'brief_mode':'NEXT_SESSION_PREP','source_session_date':'2026-07-31','target_session_date':'2026-08-03'},api_key='k',_llm=inline,async_narrative=True)
    assert called['n']==0
    assert out['narrative_status']=='ASYNC_PENDING'
    assert out['generation_timing']['ai_call'] < 500
    assert scheduled['target_session_date']=='2026-08-03'

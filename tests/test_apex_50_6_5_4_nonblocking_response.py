import time


def test_deferred_async_generation_does_not_touch_job_store(monkeypatch):
    from engine import morning_brief as mb
    import engine.async_narrative as an

    monkeypatch.setenv('ANTHROPIC_API_KEY', 'k')
    monkeypatch.setattr(mb, 'build_deterministic', lambda **kw: (
        type('D', (), {'to_dict': lambda self: {'spot': 7489.52, 'levels': [], 'trade_map': [], 'expected_move': {}, 'gamma_regime': 'unknown'}})(),
        'SECTIONS', {'spot': 7489.52}
    ))
    monkeypatch.setattr(an, 'get_job', lambda *_a, **_k: (_ for _ in ()).throw(AssertionError('job store must not be read inline')))
    monkeypatch.setattr(an, 'schedule', lambda *_a, **_k: (_ for _ in ()).throw(AssertionError('scheduler must not run inline')))

    out = mb.generate_morning_brief(
        cache={}, narrative_cache={},
        session_context={'brief_mode':'NEXT_SESSION_PREP','source_session_date':'2026-07-31','target_session_date':'2026-08-03'},
        api_key='k', async_narrative=True, defer_async_enqueue=True,
    )
    assert out['narrative_status'] == 'ASYNC_PENDING'
    assert out['anthropic_telemetry']['outcome'] == 'ASYNC_DEFERRED'
    req = out['_async_narrative_request']
    assert req['target_session_date'] == '2026-08-03'
    assert req['brief_mode'] == 'NEXT_SESSION_PREP'


def test_enqueue_nonblocking_returns_before_schedule_work(monkeypatch):
    import engine.async_narrative as an
    called = {'done': False}

    def slow_schedule(**kw):
        time.sleep(0.25)
        called['done'] = True
        return {'status': 'PENDING'}

    monkeypatch.setattr(an, 'schedule', slow_schedule)
    key = 'SPX:2099-01-01:NEXT_SESSION_PREP'
    started = time.perf_counter()
    out = an.enqueue_nonblocking(
        key=key, prompt='x', api_key='k', model='m',
        target_session_date='2099-01-01', brief_mode='NEXT_SESSION_PREP', force=True,
    )
    elapsed = time.perf_counter() - started
    assert out['nonblocking'] is True
    assert elapsed < 0.10
    assert called['done'] is False
    deadline = time.time() + 1
    while time.time() < deadline and not called['done']:
        time.sleep(0.02)
    assert called['done'] is True


def test_route_source_defers_enqueue_until_after_archive():
    from pathlib import Path
    src = Path('app.py').read_text()
    assert 'defer_async_enqueue=True' in src
    archive = src.index('payload["forecast_archive"] = save_morning_snapshot')
    enqueue = src.index('enqueue_nonblocking(**async_request)')
    response = src.index('return jsonify(payload)', enqueue)
    assert archive < enqueue < response
    assert '"anthropic_waited_inline": False' in src
    assert '"response_ready_ms": response_ready_ms' in src

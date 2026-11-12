import importlib
from pathlib import Path

from engine import container_memory_limit_event_investigation as mem


def _s(at, seconds, mx, identity='boot:1:2', anon=100, file=500, oom=0):
    return {'at':at, 'monotonic': seconds, 'cgroup_identity':identity,
            'events':{'max':mx,'oom':oom,'oom_kill':0,'low':0,'high':0,'oom_group_kill':0},
            'current_bytes':anon+file, 'peak_bytes':1000,'limit_bytes':1000,
            'stat':{'anon':anon,'file':file,'active_file':300,'inactive_file':200,'kernel':20,'slab':10},
            'psi':{'some_avg10':0.0,'full_avg10':0.0}}


def test_historical_max_not_inferred():
    mem._HISTORY.clear(); mem._INTERVALS.clear()
    original=mem.sample
    try:
        mem.sample=lambda *a,**kw:_s('2026-11-12T12:00:00+00:00',1,27)
        x=mem.observe(); assert x['status']=='BASELINE_ESTABLISHED_NO_EVENT_TIME_INFERRED';assert x['baseline_cumulative_max']==27
        mem.sample=lambda *a,**kw:_s('2026-11-12T12:01:00+00:00',61,27)
        x=mem.observe();assert x['status']=='NO_NEW_MAX_EVENTS';assert x['max_events_since_process_local_baseline']==0
    finally:
        mem.sample=original;mem._HISTORY.clear();mem._INTERVALS.clear()


def test_new_limit_event_and_distinguish_oom():
    before=_s('2026-11-12T12:00:00+00:00',0,27)
    after=_s('2026-11-12T12:01:00+00:00',60,30,anon=120,file=700)
    got=mem.compare(before,after)
    assert got['status']=='NEW_MAX_EVENTS_OBSERVED'
    assert got['event_deltas']['max']==3 and got['event_deltas']['oom_kill']==0
    assert got['anon_delta_bytes']==20 and got['file_delta_bytes']==200


def test_identity_change_and_counter_reset():
    a=_s('2026-11-12T12:00:00+00:00',1,27)
    assert mem.compare(a,_s('2026-11-12T12:01:00+00:00',2,28,'new:1:2'))['status']=='CGROUP_IDENTITY_CHANGED_OR_UNAVAILABLE'
    assert mem.compare(a,_s('2026-11-12T12:01:00+00:00',2,0))['status']=='COUNTER_RESET_OR_REPLACED'
    assert mem.compare(a,_s('2026-11-12T12:01:00+00:00',0,28))['status']=='NONMONOTONIC_SAMPLE'


def test_phase_is_temporal_only():
    interval=mem.compare(_s('2026-11-12T12:00:00+00:00',1,27),_s('2026-11-12T12:01:00+00:00',61,28))
    phase={'processes':[{'pid':41,'process_start_ticks':123,'phases':{'FULL_SCAN':{'last_completed':{
        'observed_at':'2026-11-12T12:00:30+00:00','rss_delta_kib':1500}}}}]}
    got=mem.phase_context(interval,phase)
    assert got['causation_established'] is False
    assert got['matching_last_completions'][0]['pid']==41
    assert mem.phase_context(interval,{'processes':[]})['status']=='NO_LAST_COMPLETION_IN_INTERVAL'


def test_real_cgroup_sample_from_fixture(tmp_path):
    (tmp_path/'memory.events').write_text('low 0\nhigh 0\nmax 27\noom 0\noom_kill 0\n')
    (tmp_path/'memory.stat').write_text('anon 100\nfile 500\nactive_file 300\ninactive_file 200\n')
    (tmp_path/'memory.current').write_text('600\n')
    (tmp_path/'memory.max').write_text('1000\n')
    (tmp_path/'memory.peak').write_text('1000\n')
    (tmp_path/'memory.pressure').write_text('some avg10=0.0 avg60=0.0 total=0\nfull avg10=0.0 avg60=0.0 total=0\n')
    got=mem.sample(tmp_path)
    assert got['events']['max']==27 and got['stat']['file']==500 and got['current_bytes']==600


def test_fail_open_missing_files(tmp_path):
    assert mem.sample(tmp_path) is None
    mem._HISTORY.clear(); mem._INTERVALS.clear()
    assert mem.observe(root=tmp_path)['status']=='CGROUP_SAMPLE_UNAVAILABLE'


def test_bounded_data():
    mem._HISTORY.clear(); mem._INTERVALS.clear()
    original=mem.sample
    try:
        for i in range(25):
            mem.sample=lambda *a,i=i,**kw:_s(f'2026-11-12T12:{i:02d}:00+00:00',i+1,i)
            result=mem.observe()
        assert result['sample_count']==16
        assert len(result['new_max_event_intervals'])==8
    finally:
        mem.sample=original;mem._HISTORY.clear();mem._INTERVALS.clear()


def test_app_wiring_static():
    app=Path(__file__).resolve().parents[1].joinpath('app.py').read_text()
    assert '"container_memory_limit_event_investigation"' in app
    assert 'container_memory_limit_event_observe(' in app

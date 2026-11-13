from pathlib import Path
from engine import web_process_allocation_retention_audit as m


def _point(pid=41, ticks=200, mono=5, rss=100, anon=50, blocks=1000):
    return {"pid": pid, "start_ticks": ticks, "monotonic": mono, "observed_at": "2026-11-13T21:00:00Z",
            "process": {"rss_kib": rss, "rss_anon_kib": anon, "allocated_blocks": blocks},
            "cgroup": {"anon_bytes": anon * 1024, "file_bytes": 123}}


def test_comparison_tracks_anon_and_blocks_without_claiming_leak():
    result=m.compare(_point(),_point(mono=45,rss=150,anon=65,blocks=1400))
    assert result['comparable'] is True
    assert result['process_deltas']['rss_anon_kib'] == 15
    assert result['process_deltas']['allocated_blocks'] == 400
    assert result['cgroup_deltas']['anon_bytes'] == 15360
    assert result['status'] == 'COMPARABLE_TREND_NOT_CAUSAL'


def test_pid_reuse_and_missing_identity_refused():
    assert not m.compare(_point(),_point(ticks=201))['comparable']
    assert not m.compare(_point(),_point(ticks=None))['comparable']
    assert not m.compare(_point(mono=45),_point(mono=5))['comparable']


def test_proc_stat_parsing_comm_with_spaces(tmp_path):
    folder=tmp_path/'42'; folder.mkdir()
    parts=['S']+['0']*18+['123456']+['0']*5
    (folder/'stat').write_text('42 (web process with spaces) '+' '.join(parts))
    assert m._process_start_ticks(42,tmp_path)==123456


def test_bounded_history_and_restart(monkeypatch):
    m._HISTORY.clear()
    points=iter([_point(mono=i*31) for i in range(20)])
    monkeypatch.setattr(m,'sample',lambda **_:next(points))
    for _ in range(20):
        r=m.observe()
    assert r['history_samples']==16
    assert r['oldest_to_current']['comparable'] is True
    monkeypatch.setattr(m,'sample',lambda **_: _point(ticks=201,mono=650))
    r=m.observe()
    assert r['status']=='FIRST_PROCESS_SAMPLE'
    assert r['history_samples']==1
    m._HISTORY.clear()


def test_missing_proc_does_not_fail_or_infer_identity(tmp_path):
    got=m.observe(proc_root=tmp_path,cgroup_root=tmp_path,pid=999999,monotonic=12)
    assert got['status']=='PROCESS_IDENTITY_UNVERIFIED'
    assert got['db_reads'] is False and got['calls_gc_collect'] is False
    m._HISTORY.clear()


def test_wiring_and_no_trade_changes():
    src=(Path(__file__).resolve().parents[1]/'app.py').read_text()
    assert '"web_process_allocation_retention_audit"' in src
    assert 'web_allocation_retention_observe()' in src
    assert src.index('web_allocation_retention_observe()') < src.index('_health_construction_end_ns =')

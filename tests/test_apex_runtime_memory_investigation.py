from engine import runtime_memory_investigation as m


def _write(root, *, current=990, anon=810, file=100, inactive=40, max_events=0, kills=0):
    (root / 'memory.current').write_text(str(current))
    (root / 'memory.max').write_text('1000')
    (root / 'memory.peak').write_text('999')
    (root / 'memory.stat').write_text(f'anon {anon}\nfile {file}\ninactive_file {inactive}\nslab 12\n')
    (root / 'memory.events').write_text(f'max {max_events}\noom 0\noom_kill {kills}\n')


def test_attribution_distinguishes_cgroup_anon_from_file_cache(tmp_path):
    m._SAMPLES.clear()
    _write(tmp_path)
    result = m.inspect(cgroup_root=tmp_path, pid=99999999, monotonic=100)
    assert result['cgroup']['accounting']['anon_bytes'] == 810
    assert result['cgroup']['accounting']['file_bytes'] == 100
    assert result['cgroup']['accounting']['inactive_file_bytes'] == 40
    assert result['web_process']['available'] is False
    assert result['status'] == 'SINGLE_SAMPLE_NO_CAUSAL_ATTRIBUTION'
    assert result['automatic_reclamation'] is False
    assert result['db_reads'] is False


def test_counter_delta_and_bounded_trend(tmp_path):
    m._SAMPLES.clear()
    _write(tmp_path, current=700, anon=400, max_events=20)
    m.inspect(cgroup_root=tmp_path, pid=99999999, monotonic=100)
    _write(tmp_path, current=990, anon=850, max_events=23)
    result = m.inspect(cgroup_root=tmp_path, pid=99999999, monotonic=131)
    assert result['status'] == 'MEMORY_LIMIT_EVENTS_INCREASING'
    assert result['bounded_trend']['max_events_since_first_sample'] == 3
    assert result['bounded_trend']['cgroup_anon_delta_bytes'] == 450
    assert result['bounded_trend']['sample_count'] == 2


def test_missing_metrics_fail_closed_and_unlimited(tmp_path):
    m._SAMPLES.clear()
    a = m.inspect(cgroup_root=tmp_path, pid=99999999, monotonic=1)
    assert a['status'] == 'MEASUREMENTS_UNAVAILABLE'
    assert a['cgroup']['current_bytes'] is None
    _write(tmp_path)
    (tmp_path / 'memory.max').write_text('max')
    b = m.inspect(cgroup_root=tmp_path, pid=99999999, monotonic=40)
    assert b['cgroup']['limit_bytes'] is None
    assert b['execution_authority'] is False


def test_counters_reset_not_treated_as_new_events(tmp_path):
    m._SAMPLES.clear()
    _write(tmp_path, max_events=40)
    m.inspect(cgroup_root=tmp_path, pid=99999999, monotonic=5)
    _write(tmp_path, max_events=1)
    result = m.inspect(cgroup_root=tmp_path, pid=99999999, monotonic=40)
    assert result['bounded_trend']['max_events_since_first_sample'] is None
    assert result['status'] == 'TREND_OBSERVED_CAUSE_NOT_PROVEN'


def test_no_proc_or_database_enumeration(monkeypatch, tmp_path):
    m._SAMPLES.clear()
    _write(tmp_path)
    observed = m.inspect(cgroup_root=tmp_path, pid=99999999, monotonic=50)
    assert observed['stage_trace']['read_by_endpoint'] is False
    assert observed['sqlite']['measurement'] == 'NOT_SAMPLED'


def test_existing_monitor_collects_memory_stat_without_writes(tmp_path, monkeypatch):
    from engine import runtime_memory_attribution as existing
    _write(tmp_path, current=777, anon=600, file=160)
    monkeypatch.setenv('APEX_MEMORY_CGROUP_PATH', str(tmp_path))
    result = existing._cgroup()
    assert result['memory_stat']['anon_bytes'] == 600
    assert result['memory_stat']['file_bytes'] == 160
    assert result['events']['max'] == 0


def test_health_route_wiring_static():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / 'app.py').read_text()
    assert 'from engine.runtime_memory_investigation import inspect as runtime_memory_investigation' in source
    assert '"runtime_memory_investigation": runtime_memory_investigation()' in source

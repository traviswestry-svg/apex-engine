import json
from engine import runtime_memory_attribution as m


def test_snapshot_safe_for_missing_pids(monkeypatch):
    monkeypatch.setattr(m, '_cgroup', lambda: {'current_bytes': 100, 'limit_bytes': 200, 'peak_bytes': 100, 'usage_pct': 50, 'events': {}})
    result = m.snapshot(99999999, 99999998)
    assert result['processes']['scanner']['memory'] is None
    assert result['execution_authority'] is False


def test_bounded_file_rotation(tmp_path):
    path = tmp_path / 'memory.jsonl'
    m.append_bounded(path, {'one': 'x' * 30}, max_bytes=10)
    m.append_bounded(path, {'two': 2}, max_bytes=10)
    assert json.loads(path.read_text()) == {'two': 2}
    assert (tmp_path / 'memory.jsonl.previous').exists()


def test_monitor_warns_without_mutation(tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'snapshot', lambda *args: {'cgroup': {'usage_pct': 95, 'events': {'oom_kill': 0}}, 'processes': {}, 'execution_authority': False})
    path = tmp_path / 'monitor.jsonl'
    m.monitor(1, 2, iterations=1, output=str(path))
    row = json.loads(path.read_text().strip())
    assert row['severity'] == 'CRITICAL'
    assert row['execution_authority'] is False

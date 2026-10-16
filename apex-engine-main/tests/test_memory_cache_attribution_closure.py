"""Regression tests for non-mutating cgroup cache attribution."""
from engine import runtime_memory_attribution as m


def test_cgroup_reports_raw_and_noninactive_usage(tmp_path, monkeypatch):
    (tmp_path / "memory.current").write_text("3600")
    (tmp_path / "memory.max").write_text("4000")
    (tmp_path / "memory.peak").write_text("3800")
    (tmp_path / "memory.stat").write_text("anon 1000\ninactive_file 1600\nfile 2000\n")
    (tmp_path / "memory.events").write_text("oom 0\noom_kill 0\n")
    monkeypatch.setenv("APEX_MEMORY_CGROUP_PATH", str(tmp_path))
    result = m._cgroup()
    assert result["usage_pct"] == 90.0
    assert result["noninactive_pct"] == 50.0
    assert result["inactive_file_bytes"] == 1600
    assert result["events"]["oom_kill"] == 0


def test_missing_memory_stat_does_not_invent_adjusted_usage(tmp_path, monkeypatch):
    (tmp_path / "memory.current").write_text("3600")
    (tmp_path / "memory.max").write_text("4000")
    monkeypatch.setenv("APEX_MEMORY_CGROUP_PATH", str(tmp_path))
    result = m._cgroup()
    assert result["usage_pct"] == 90.0
    assert result["noninactive_pct"] is None


def test_inactive_file_cannot_exceed_current(tmp_path, monkeypatch):
    (tmp_path / "memory.current").write_text("2000")
    (tmp_path / "memory.max").write_text("4000")
    (tmp_path / "memory.stat").write_text("inactive_file 9000\n")
    monkeypatch.setenv("APEX_MEMORY_CGROUP_PATH", str(tmp_path))
    assert m._cgroup()["noninactive_pct"] == 0.0


def test_monitor_preserves_raw_threshold_and_includes_context(monkeypatch, capsys):
    writes = []
    monkeypatch.setattr(m, "snapshot", lambda *a, **k: {"cgroup": {"usage_pct": 83.8, "noninactive_pct": 52.1, "inactive_file_bytes": 1400, "events": {"oom_kill": 0}}})
    monkeypatch.setattr(m, "append_bounded", lambda path, record: writes.append(record))
    m.monitor(41, 42, iterations=1, sleep=lambda _: None)
    assert writes[0]["severity"] == "WARN"
    assert "noninactive_pct=52.1" in capsys.readouterr().out

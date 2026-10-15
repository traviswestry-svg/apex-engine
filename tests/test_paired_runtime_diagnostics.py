import importlib.util
import json
import sys
import types
from pathlib import Path

def load(monkeypatch):
    fake = types.ModuleType("engine.runtime_memory_attribution")
    snapshots = iter([{"processes":{"scanner":{"memory":{"rss_kib":100,"pss_kib":80,"private_dirty_kib":70}}},"cgroup":{"current_bytes":1000}}, {"processes":{"scanner":{"memory":{"rss_kib":120,"pss_kib":85,"private_dirty_kib":75}}},"cgroup":{"current_bytes":1100}}])
    fake.snapshot = lambda **kwargs: next(snapshots)
    writes=[]
    fake.append_bounded=lambda path,record: writes.append((path,record))
    monkeypatch.setitem(sys.modules,"engine.runtime_memory_attribution",fake)
    spec=importlib.util.spec_from_file_location("paired_test_module",Path(__file__).resolve().parents[1]/"engine/paired_runtime_diagnostics.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module,writes

def test_paired_delta(monkeypatch):
    m,writes=load(monkeypatch)
    token=m.begin_stage("cycle-1","SETTLEMENT_PASS")
    m.end_stage("cycle-1","SETTLEMENT_PASS",token)
    assert writes[0][1]["delta_kib"] == {"rss_kib":20,"pss_kib":5,"private_dirty_kib":5}
    assert writes[0][1]["execution_authority"] is False

def test_coverage_event(monkeypatch):
    m,writes=load(monkeypatch)
    m.scan_event("scan-1","SKIPPED",reason="LOCK_BUSY")
    assert writes[0][1]["reason"]=="LOCK_BUSY"
    assert writes[0][1]["decision_authority"] is False

def test_write_failure_is_fail_open(monkeypatch):
    m,writes=load(monkeypatch)
    m.append_bounded=lambda *args: (_ for _ in ()).throw(OSError("unavailable"))
    m.scan_event("scan-1","ATTEMPT")

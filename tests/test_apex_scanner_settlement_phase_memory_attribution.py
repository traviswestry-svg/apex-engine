"""Shadow-only phase attribution / same-process integrity regressions."""
from __future__ import annotations
import json
from pathlib import Path
from engine import scanner_settlement_phase_memory_attribution as mod
from engine import paired_runtime_diagnostics as paired
from engine import flow_settlement_scheduler as settlement


def pair(pid=7, ticks=111, stage="FULL_SCAN", a=100, b=120, *, c0=1000, c1=1200, verified=True):
    return {"stage":stage,"cycle_id":"c1","observed_at":"2026-11-10T19:00:00Z",
            "process_pid":pid,"process_start_ticks":ticks,"process_identity_verified":verified,
            "before":{"rss_kib":a,"private_dirty_kib":70},
            "after":{"rss_kib":b,"private_dirty_kib":80},
            "cgroup_before":{"current_bytes":c0,"memory_stat":{"anon_bytes":800,"file_bytes":100},"events":{"max":2,"oom_kill":0}},
            "cgroup_after":{"current_bytes":c1,"memory_stat":{"anon_bytes":850,"file_bytes":240},"events":{"max":2,"oom_kill":0}},
            "outcome":"COMPLETED","elapsed_ms":35.2}


def test_scanner_and_settlement_same_instance():
    out = mod.summarize([pair(), pair(stage="SETTLEMENT_PASS",a=120,b=170)])
    assert out["status"] == "PHASE_PAIRS_AVAILABLE"
    process = out["processes"][0]
    assert process["paired_records"] == 2
    assert process["phases"]["FULL_SCAN"]["last_completed"]["rss_delta_kib"] == 20
    assert process["phases"]["SETTLEMENT_PASS"]["last_completed"]["rss_delta_kib"] == 50
    assert process["same_process_boundary_rss_delta_kib"] == 70
    assert process["phases"]["FULL_SCAN"]["last_completed"]["cgroup_file_delta_bytes"] == 140


def test_pid_reuse_never_combines():
    out=mod.summarize([pair(pid=7,ticks=111), pair(pid=7,ticks=222,stage="SETTLEMENT_PASS")])
    assert len(out['processes']) == 2
    assert all(p['paired_records'] == 1 for p in out['processes'])
    assert out['processes'][0]['phases']['FULL_SCAN']['sample_count'] == 0


def test_legacy_unverified_excluded():
    assert mod.summarize([pair(verified=False), {"stage":"FULL_SCAN","process_pid":8}])['status'] == 'NO_VERIFIED_PHASE_PAIRS'


def test_bounded_reader_and_corrupt_lines(tmp_path):
    p=tmp_path/'pairs.jsonl'
    p.write_bytes(b'junk\n' + json.dumps(pair()).encode()+b'\n'+ b'{bad\n')
    out=mod.inspect(path=p)
    assert out['verified_records']==1
    assert out['bounded_read_max_bytes']==131072
    assert out['read_only'] and not out['execution_authority']


def test_missing_file_is_explicit(tmp_path):
    assert mod.inspect(path=tmp_path/'absent')['status']=='PHASE_TRACE_UNAVAILABLE'


def test_reader_skips_partial_leading_record(tmp_path, monkeypatch):
    monkeypatch.setattr(mod,'READ_BYTES',256)
    p=tmp_path/'pairs.jsonl'
    data=(json.dumps(pair())+'\n').encode()
    p.write_bytes(data + data)
    out=mod.inspect(path=p)
    assert out['verified_records'] <= 1


def test_scheduler_instruments_only_real_settlement_call(monkeypatch):
    stages=[]
    import engine.paired_runtime_diagnostics as diag
    monkeypatch.setattr(diag,'new_cycle_id',lambda prefix: 'settlement-1')
    monkeypatch.setattr(diag,'begin_stage',lambda cycle,stage: stages.append(('start',stage)) or 'token')
    monkeypatch.setattr(diag,'end_stage',lambda cycle,stage,token, outcome: stages.append(('end',stage,outcome)))
    monkeypatch.setattr(settlement.feature_store_writer,'settle_pending_labels',lambda **kw: {'state':'COMPLETED','labelled':0})
    s=settlement.FlowSettlementScheduler(enabled=True,interval_seconds=300)
    assert s.run_if_due(force=True)['state']=='COMPLETED'
    assert stages==[('start','SETTLEMENT_PASS'),('end','SETTLEMENT_PASS','COMPLETED')]
    s.run_if_due(force=False,monotonic_now=1_000_000)
    # The cadence slot can be claimed again with artificially advanced monotonic time.


def test_scheduler_diagnostic_failure_does_not_change_settlement(monkeypatch):
    import engine.paired_runtime_diagnostics as diag
    monkeypatch.setattr(diag,'begin_stage',lambda *args: (_ for _ in ()).throw(RuntimeError('test')))
    monkeypatch.setattr(settlement.feature_store_writer,'settle_pending_labels',lambda **kw:{'state':'COMPLETED','labelled':1})
    s=settlement.FlowSettlementScheduler(enabled=True)
    assert s.run_if_due(force=True)['state']=='COMPLETED'


def test_integration_wiring_and_no_route_duplication():
    root=Path(__file__).resolve().parents[1]
    app=(root/'app.py').read_text()
    sched=(root/'engine/flow_settlement_scheduler.py').read_text()
    assert '"scanner_settlement_phase_memory_attribution": scanner_settlement_phase_memory_inspect()' in app
    assert 'end_stage(_phase_id, "SETTLEMENT_PASS"' in sched
    assert app.count('"scanner_settlement_phase_memory_attribution":') == 1

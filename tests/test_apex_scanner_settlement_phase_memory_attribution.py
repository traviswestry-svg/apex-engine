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


def test_scheduler_skips_instrumentation_when_not_due_and_records_errors(monkeypatch):
    stages = []
    monkeypatch.setattr(paired, 'new_cycle_id', lambda prefix: 'cycle')
    monkeypatch.setattr(paired, 'begin_stage', lambda cycle, stage: stages.append('start') or 'token')
    monkeypatch.setattr(paired, 'end_stage', lambda cycle, stage, token, outcome: stages.append(outcome))
    monkeypatch.setattr(settlement.feature_store_writer, 'settle_pending_labels',
                        lambda **kw: (_ for _ in ()).throw(RuntimeError('failure')))
    s = settlement.FlowSettlementScheduler(enabled=True, interval_seconds=300)
    assert s.run_if_due(monotonic_now=100)['state'] == 'ERROR'
    assert s.run_if_due(monotonic_now=101)['cadence_skips'] == 1
    assert stages == ['start', 'ERROR']


def test_integration_wiring_and_no_route_duplication():
    root=Path(__file__).resolve().parents[1]
    app=(root/'app.py').read_text()
    sched=(root/'engine/flow_settlement_scheduler.py').read_text()
    assert '"scanner_settlement_phase_memory_attribution": scanner_settlement_phase_memory_inspect()' in app
    assert 'end_stage(_phase_id, "SETTLEMENT_PASS"' in sched
    assert app.count('"scanner_settlement_phase_memory_attribution":') == 1


def test_rejection_breakdown_explains_zero_verified():
    legacy = pair(); legacy.pop('process_start_ticks')
    nonverified = pair(verified=False)
    other = pair(stage='UNKNOWN')
    no_rss = pair(); no_rss['before'].pop('rss_kib')
    wrong_schema = pair(); wrong_schema['schema'] = 'unknown.schema'
    out = mod.summarize([legacy, nonverified, other, no_rss, wrong_schema, 3], parse_failures=2,
                        truncated_tail=True, read_lines=8)
    d = out['reconciliation']
    assert out['status'] == 'NO_VERIFIED_PHASE_PAIRS'
    assert d['classification_counts'] == {
        'MALFORMED_JSON': 2, 'MISSING_OR_INVALID_PROCESS_IDENTITY': 1,
        'MISSING_PROCESS_RSS': 1, 'NON_OBJECT_JSON_RECORD': 1,
        'UNSUPPORTED_PAIR_SCHEMA': 1, 'UNSUPPORTED_STAGE': 1,
        'UNVERIFIED_PROCESS_IDENTITY': 1}
    assert d['tail_window_truncated'] is True
    assert d['strict_identity_matching']
    assert d['evaluated_lines'] == 8


def test_verified_scan_only_is_not_misreported_as_same_process_both_phases():
    out = mod.summarize([pair(stage='FULL_SCAN')])
    assert out['status'] == 'PHASE_PAIRS_AVAILABLE'
    assert out['reconciliation']['same_process_scan_and_settlement_present'] is False


def test_same_pid_different_process_start_does_not_count_cross_phase():
    out = mod.summarize([pair(stage='FULL_SCAN', ticks=10),
                         pair(stage='SETTLEMENT_PASS', ticks=11)])
    assert out['reconciliation']['same_process_scan_and_settlement_present'] is False
    assert len(out['processes']) == 2


def test_bounded_tail_rejection_counts_without_reading_full_file(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'READ_BYTES', 2048)
    p = tmp_path / 'pairs.jsonl'
    old = json.dumps({'stage':'LEGACY', 'padding':'x'*2300}) + '\n'
    p.write_text(old*30 + json.dumps({'stage':'FULL_SCAN', 'schema':'apex.memory_pair.v1'}) + '\n'
                 + '{bad json\n')
    out = mod.inspect(path=p)
    assert out['status'] == 'NO_VERIFIED_PHASE_PAIRS'
    d = out['reconciliation']
    assert d['tail_window_truncated'] is True
    assert d['classification_counts']['MALFORMED_JSON'] == 1
    assert d['classification_counts']['MISSING_OR_INVALID_PROCESS_IDENTITY'] == 1
    assert out['bounded_read_max_bytes'] == 2048


def test_writer_provides_compatible_identity_diagnostic(tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_MEMORY_PAIR_PATH', str(tmp_path / 'memory.jsonl'))
    before = {'processes': {'scanner': {'memory': {'rss_kib': 123, 'private_dirty_kib': 60}}},
              'cgroup': {'current_bytes': 1234, 'memory_stat': {'anon_bytes': 111}, 'events': {'max':0}}}
    after = {'processes': {'scanner': {'memory': {'rss_kib': 132, 'private_dirty_kib': 62}}},
             'cgroup': {'current_bytes': 1256, 'memory_stat': {'anon_bytes': 120}, 'events': {'max':0}}}
    snapshots = iter([before, after])
    monkeypatch.setattr(paired, 'snapshot', lambda **kw: next(snapshots))
    monkeypatch.setattr(paired, '_process_start_ticks', lambda pid: 987)
    started = paired.begin_stage('cycle-1', 'FULL_SCAN')
    paired.end_stage('cycle-1', 'FULL_SCAN', started)
    result = mod.inspect(path=tmp_path / 'memory.jsonl')
    assert result['verified_records'] == 1
    assert result['reconciliation']['classification_counts']['VERIFIED'] == 1
    raw = json.loads((tmp_path / 'memory.jsonl').read_text())
    assert raw['identity_diagnostic'] == 'VERIFIED'
    assert raw['process_identity_verified'] is True
    assert raw['process_start_ticks'] == 987


def test_writer_missing_start_time_is_explained_not_promoted(tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_MEMORY_PAIR_PATH', str(tmp_path / 'memory.jsonl'))
    snap = {'processes': {'scanner': {'memory': {'rss_kib': 123}}},
            'cgroup': {'current_bytes': 100}}
    monkeypatch.setattr(paired, 'snapshot', lambda **kw: snap)
    monkeypatch.setattr(paired, '_process_start_ticks', lambda pid: None)
    token = paired.begin_stage('cycle-1', 'SETTLEMENT_PASS')
    paired.end_stage('cycle-1', 'SETTLEMENT_PASS', token)
    output = mod.inspect(path=tmp_path / 'memory.jsonl')
    assert output['verified_records'] == 0
    assert output['reconciliation']['classification_counts']['MISSING_OR_INVALID_PROCESS_IDENTITY'] == 1
    assert json.loads((tmp_path / 'memory.jsonl').read_text())['identity_diagnostic'] == 'PROCESS_START_UNAVAILABLE'


def test_writer_rejects_changed_process_identity(tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_MEMORY_PAIR_PATH', str(tmp_path / 'memory.jsonl'))
    monkeypatch.setattr(paired, 'snapshot', lambda **kw: {'processes': {'scanner': {'memory': {'rss_kib': 123}}}})
    ticks = iter([100, 101])
    monkeypatch.setattr(paired, '_process_start_ticks', lambda pid: next(ticks))
    token = paired.begin_stage('cycle', 'FULL_SCAN')
    paired.end_stage('cycle', 'FULL_SCAN', token)
    raw = json.loads((tmp_path / 'memory.jsonl').read_text())
    assert raw['identity_diagnostic'] == 'PROCESS_IDENTITY_CHANGED'
    assert raw['process_identity_verified'] is False
    assert mod.inspect(path=tmp_path / 'memory.jsonl')['verified_records'] == 0

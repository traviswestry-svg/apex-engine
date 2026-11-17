import importlib.util
import json
from pathlib import Path
import pytest

FILE = Path(__file__).parents[1] / 'scripts/apex_stage3b0_compatibility_audit.py'
spec = importlib.util.spec_from_file_location('stage3b0', FILE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

@pytest.mark.parametrize('raw', [b'{}', b'{"a":1, "b": [1,2]}', b'{"unicode":"\xc3\xa9"}', b'{"number":1e-9, "key":"x"}', b'[]'])
@pytest.mark.parametrize('level', [6,9])
def test_byte_exact(raw, level):
    assert m.strict_zlib_decode(__import__('zlib').compress(raw, level)) == raw
    assert m.roundtrip(raw, level)['byte_exact']

def test_reject_trailing():
    import zlib
    with pytest.raises(ValueError): m.strict_zlib_decode(zlib.compress(b'abc') + b'extra')

def test_reject_truncated():
    import zlib
    with pytest.raises(ValueError): m.strict_zlib_decode(zlib.compress(b'abc')[:-2])

def test_decompression_bomb_cap():
    import zlib
    with pytest.raises(ValueError): m.strict_zlib_decode(zlib.compress(b'x'*20000), max_output_bytes=2000)

def test_reject_input_limit():
    import zlib
    with pytest.raises(ValueError): m.strict_zlib_decode(zlib.compress(b'xxx'), max_output_bytes=4)

def test_benchmark_no_raw_payload_export():
    report = m.benchmark_fixture('test', {'a': 'test'*64}, repetitions=2)
    assert report['synthetic_only'] and report['no_source_payloads']
    assert all(x['byte_exact'] for x in report['benchmarks'])
    assert 'testtest' not in json.dumps(report)

def test_missing_source_fails_closed(tmp_path):
    result=m.produce(tmp_path, iterations=1)
    assert result['source_reference_inventory']['complete'] is False
    assert result['migration_feasibility']['status'] == 'BLOCKED_RESEARCH_ONLY'
    assert not result['migration_feasibility']['production_migration_authorized']
    assert result['guardrails']['sqlite_connections'] == 0

def test_reference_hints(tmp_path):
    d=tmp_path/'engine';d.mkdir()
    (d/'reader.py').write_text('x=json.loads(row["snapshot_json"])\n')
    inv=m.source_inventory(tmp_path)
    assert inv['complete']
    assert inv['references']['decisions.snapshot_json']['sample'][0]['kind_hint'].startswith('POTENTIAL')
    assert not inv['references']['decisions.snapshot_json']['classification_verified']

def test_limits(tmp_path):
    with pytest.raises(ValueError):m.produce(tmp_path,iterations=51)

def test_existing_archive_detection(tmp_path):
    d=tmp_path/'engine';d.mkdir()
    (d/'historical_payload_archive.py').write_text('ZLIB_9 source_sha256 trg_historical_payload_archive_no_delete trg_historical_payload_archive_no_update\ndef retrieve_archived_payload(): pass\n"TRIGGER_EVIDENCE" "DECISION_SNAPSHOT"')
    c=m.check_existing_contracts(tmp_path)
    assert c['historical_archive_source_present']
    assert c['existing_archive_immutable_triggers']
    assert not c['compatibility_verified']

def test_output_protection(tmp_path):
    assert m.main(['--repo-root',str(tmp_path), '--output',str(tmp_path.parent/'stage3b0-test-output.json'),'--benchmark-iterations','1']) == 0
    with pytest.raises(SystemExit):
        m.main(['--repo-root',str(tmp_path),'--output',str(tmp_path/'inside.json')])
    (tmp_path.parent/'stage3b0-test-output.json').unlink()

def test_all_expected_target_columns():
    assert len(m.TARGETS)==10
    assert 'decisions.snapshot_json' in m.TARGETS
    assert 'gamma_observational_snapshots.snapshot_json' in m.TARGETS

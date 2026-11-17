#!/usr/bin/env python3
"""APEX Stage 3B.1: offline immutable archive reader/replay compatibility audit.

Only reads repo source. All SQLite writes occur in TemporaryDirectory fixture DBs.
Never connects to /data, archives real payloads, or authorizes production cutover.
"""
from __future__ import annotations
import argparse
import ast
import contextlib
import hashlib
import json
import re
import sqlite3
import tempfile
import zlib
from pathlib import Path

SCHEMA = 'apex.stage3b1_immutable_archive_reader_replay.v1'
ARCHIVE_SOURCE = Path('engine/historical_payload_archive.py')
TARGETS = {'DECISION_SNAPSHOT': 'decisions.snapshot_json', 'TRIGGER_EVIDENCE': 'observed_trade_triggers.evidence_json'}
MAX_SOURCE_BYTES = 300_000
MAX_READER_FILES = 700
MAX_READER_BYTES = 1_500_000
MAX_REFERENCE_RESULTS = 24


def extract_functions(source: str):
    """Load only existing archive retrieval/decode definitions, not package imports."""
    tree = ast.parse(source)
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in {'retrieve_archived_payload', '_decompress'}]
    if {n.name for n in nodes} != {'retrieve_archived_payload', '_decompress'}:
        raise ValueError('archive_reader_contract_missing')
    # Do not execute import-time initialization and do not load unrelated module functions.
    ns = {'Path': Path, 'sqlite3': sqlite3, 'hashlib': hashlib, 'zlib': zlib,
          'ARCHIVE_DB': Path('__offline_placeholder__')}
    @contextlib.contextmanager
    def connect(path, *, read_only=False, wal=False, heal=False):
        if not read_only or wal or heal:
            raise AssertionError('non_read_only_archive_open')
        conn = sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True)
        try:
            yield conn
        finally:
            conn.close()
    ns['canonical_connect'] = connect
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, '<existing_archive_functions>', 'exec'), ns)
    return ns['retrieve_archived_payload']


def make_fixture_db(path: Path):
    with contextlib.closing(sqlite3.connect(path)) as db, db:
        db.execute('''CREATE TABLE historical_payload_archive (
            payload_type TEXT NOT NULL, row_id TEXT NOT NULL,
            source_sha256 TEXT NOT NULL, source_bytes INTEGER NOT NULL,
            archive_codec TEXT NOT NULL, archive_blob BLOB NOT NULL,
            archive_bytes INTEGER NOT NULL,
            PRIMARY KEY(payload_type,row_id))''')


def write_fixture(path: Path, kind: str, row_id: str, payload: bytes, *, codec='ZLIB_9', blob=None, sha=None, length=None):
    compressed = blob if blob is not None else zlib.compress(payload, level=9)
    with contextlib.closing(sqlite3.connect(path)) as db, db:
        db.execute('''INSERT INTO historical_payload_archive
            (payload_type,row_id,source_sha256,source_bytes,archive_codec,archive_blob,archive_bytes)
            VALUES(?,?,?,?,?,?,?)''', (kind, row_id, sha or hashlib.sha256(payload).hexdigest(),
                  len(payload) if length is None else length, codec, compressed, len(compressed)))


def safe_case(name, fn):
    try:
        passed, observed = fn()
        return {'case':name, 'passed':bool(passed), 'observed':observed}
    except Exception as exc:
        return {'case':name, 'passed':False, 'observed':'UNHANDLED_EXCEPTION', 'exception_type':type(exc).__name__}


def fixture_checks(retrieve):
    """Test unmodified existing retrieval function against isolated synthetic archives."""
    with tempfile.TemporaryDirectory(prefix='apex-stage3b1-') as d:
        path = Path(d)/'synthetic_archive.db'
        make_fixture_db(path)
        decision = b'{"decision_id":"synthetic-decision","canonical_gamma_snapshot_id":"synthetic-gamma","evidence":{"alpha":1},"order":[3,2,1]}'
        trigger = '{"trigger_id":"synthetic-trigger","decision_id":"synthetic-decision","evidence":"unicode 67\u03b2","sample":true}'.encode('utf-8')
        write_fixture(path, 'DECISION_SNAPSHOT', 'synthetic-decision', decision)
        write_fixture(path, 'TRIGGER_EVIDENCE', 'synthetic-trigger', trigger)
        write_fixture(path, 'DECISION_SNAPSHOT', 'tampered', decision, blob=zlib.compress(b'{"mismatch":true}',9))
        write_fixture(path, 'TRIGGER_EVIDENCE', 'truncated', trigger, blob=zlib.compress(trigger,9)[:9])
        write_fixture(path, 'DECISION_SNAPSHOT', 'unsupported', decision, codec='UNKNOWN')
        write_fixture(path, 'DECISION_SNAPSHOT', 'invalid-utf8', b'\xff\xfe')
        write_fixture(path, 'DECISION_SNAPSHOT', 'wrong-length', decision, length=len(decision)+3)
        results=[]
        for kind,rid,payload in [('DECISION_SNAPSHOT','synthetic-decision',decision),('TRIGGER_EVIDENCE','synthetic-trigger',trigger)]:
            def check(kind=kind,rid=rid,payload=payload):
                r=retrieve(kind,rid,path=path)
                ok=r.get('ok') is True and r.get('state')=='ARCHIVE_VERIFIED' and r.get('payload','').encode('utf-8')==payload
                return ok, r.get('state')
            results.append(safe_case('byte_exact_'+kind.lower(),check))
        checks=[('missing_row','DECISION_SNAPSHOT','missing',{'ROW_NOT_ARCHIVED'}),
                ('tampered_hash','DECISION_SNAPSHOT','tampered',{'ARCHIVE_INTEGRITY_FAILURE'}),
                ('truncated_blob','TRIGGER_EVIDENCE','truncated',{'ARCHIVE_DECODE_FAILURE'}),
                ('unsupported_codec','DECISION_SNAPSHOT','unsupported',{'ARCHIVE_DECODE_FAILURE'}),
                ('wrong_length','DECISION_SNAPSHOT','wrong-length',{'ARCHIVE_INTEGRITY_FAILURE'}),
                ('invalid_utf8','DECISION_SNAPSHOT','invalid-utf8',{'ARCHIVE_DECODE_FAILURE','ARCHIVE_INTEGRITY_FAILURE'})]
        for name,kind,rid,allowed in checks:
            def check(kind=kind,rid=rid,allowed=allowed):
                r=retrieve(kind,rid,path=path)
                return r.get('ok') is False and r.get('state') in allowed and not r.get('payload'),r.get('state')
            results.append(safe_case(name,check))
        # Replay equivalence: synthetic replay projection exact field + ordering, no live engine invoked.
        def replay():
            original=json.loads(decision)
            r=retrieve('DECISION_SNAPSHOT','synthetic-decision',path=path)
            restored=json.loads(r['payload'])
            same=r['payload'].encode('utf-8')==decision and restored==original and restored['canonical_gamma_snapshot_id']=='synthetic-gamma' and restored['order']==[3,2,1]
            return same,'SYNTHETIC_ONLY'
        results.append(safe_case('synthetic_replay_and_gamma_identity',replay))
        return results


def source_inventory(repo: Path):
    needles={
        'DECISION_SNAPSHOT': ('snapshot_json','retrieve_archived_payload','DECISION_SNAPSHOT'),
        'TRIGGER_EVIDENCE': ('evidence_json','retrieve_archived_payload','TRIGGER_EVIDENCE'),
    }
    patterns={k: {n:re.compile(r'(?<![a-zA-Z_])'+re.escape(n)+r'(?![a-zA-Z_])') for n in v} for k,v in needles.items()}
    inventory={k:{'source_reference_files':[], 'archive_reader_reference_files':[], 'candidate_reader_files':[]} for k in needles}
    scanned=0; limited=False
    engine=repo/'engine'
    for path in sorted(engine.rglob('*.py')) if engine.exists() else []:
        if scanned>=MAX_READER_FILES:
            limited=True;break
        scanned+=1
        if path.stat().st_size>MAX_READER_BYTES:
            continue
        content=path.read_text(encoding='utf-8',errors='replace')
        rel=str(path.relative_to(repo))
        for kind,pats in patterns.items():
            seen={word:bool(pat.search(content)) for word,pat in pats.items()}
            entry=inventory[kind]
            if seen[list(pats)[0]]:
                if len(entry['source_reference_files'])<MAX_REFERENCE_RESULTS: entry['source_reference_files'].append(rel)
            if seen['retrieve_archived_payload']:
                if len(entry['archive_reader_reference_files'])<MAX_REFERENCE_RESULTS:entry['archive_reader_reference_files'].append(rel)
            if seen[list(pats)[0]] and not seen['retrieve_archived_payload']:
                if len(entry['candidate_reader_files'])<MAX_REFERENCE_RESULTS:entry['candidate_reader_files'].append(rel)
    return {'files_scanned':scanned, 'scope_limited':limited,'source_hints_only_not_verified_call_graph':True,'by_type':inventory}


def run(repo_root: Path):
    repo=repo_root.resolve()
    source_path=repo/ARCHIVE_SOURCE
    report={'schema':SCHEMA,'mode':'OFFLINE_SYNTHETIC_ONLY','repo_root':str(repo),
            'migration_authority':'BLOCKED_RESEARCH_ONLY','production_reader_cutover':False,
            'production_replay_performed':False,'source_database_opened':False,
            'fixture_database_writes_only':True,
            'guardrails':{'no_production_database_access':True,'no_canonical_mutation':True,
                          'no_archive_mutation':True,'no_deletion':True,'no_checkpoint':True,
                          'no_vacuum':True,'no_trade_or_execution_authority':True}}
    if not source_path.is_file() or source_path.stat().st_size>MAX_SOURCE_BYTES:
        report['status']='BLOCKED_ARCHIVE_SOURCE_MISSING_OR_OVERSIZED'; return report
    source=source_path.read_text(encoding='utf-8')
    try:
        retrieve=extract_functions(source)
    except Exception as exc:
        report['status']='BLOCKED_SOURCE_CONTRACT';report['exception_type']=type(exc).__name__;return report
    results=fixture_checks(retrieve)
    report['synthetic_existing_reader_contract']={'checks':results,'passed':sum(x['passed'] for x in results),'total':len(results),
                                                   'all_passed':all(x['passed'] for x in results)}
    report['static_reader_inventory']=source_inventory(repo)
    report['unverified_gates']=['historical_production_replay_equivalence','cross_database_gamma_and_decision_identity',
                                'production_reader_cutover_coverage','real_archive_source_correspondence',
                                'external_backup_restore_test','rollback_on_isolated_restored_copy',
                                'performance_on_production_representative_fixtures']
    report['status']='RESEARCH_ONLY_GATES_UNVERIFIED' if all(x['passed'] for x in results) else 'BLOCKED_READER_FAILURE_PATHS'
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo-root',type=Path,default=Path('.'))
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(argv)
    if a.output.resolve().is_relative_to(a.repo_root.resolve()/'engine') or a.output.resolve().is_relative_to(Path('/data')):
        p.error('output must not be in engine source or /data')
    result=run(a.repo_root)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(f"Stage 3B.1 OFFLINE report: {a.output} | migration={result['migration_authority']} | status={result['status']}")
    return 0 if result['status']=='RESEARCH_ONLY_GATES_UNVERIFIED' else 2

if __name__=='__main__':
    raise SystemExit(main())

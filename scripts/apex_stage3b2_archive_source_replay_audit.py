#!/usr/bin/env python3
"""APEX Stage 3B.2: opt-in read-only archive/source correspondence probe.

No production writer imports, archive initialization, row/identifier export, or reader cutover.
Read-only SQLite snapshots are sampled with progress-handler budgets. On-disk
legacy decisions and execution remain unchanged. This is NOT full engine replay.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sqlite3
import time
import zlib
from pathlib import Path

SCHEMA = 'apex.stage3b2_archive_source_replay_correspondence.v1'
SPECS = {
    'DECISION_SNAPSHOT': ('apex_evidence_pipeline.db', 'decisions', 'decision_id', 'snapshot_json', ('canonical_gamma_snapshot_id','decision_id','ticker','direction','action')),
    'TRIGGER_EVIDENCE': ('apex_trigger_observatory.db', 'observed_trade_triggers', 'trigger_id', 'evidence_json', ('decision_id','canonical_gamma_snapshot_id','trigger_id','direction','symbol')),
}
ALLOWED = {'ARCHIVE_VERIFIED_SOURCE_EXACT','SOURCE_MISSING','SOURCE_NULL','SOURCE_BYTES_DIFFER','ARCHIVE_DECODE_FAILURE','ARCHIVE_INTEGRITY_FAILURE','ARCHIVE_METADATA_CONFLICT','PAYLOAD_INVALID_UTF8','JSON_PARSE_FAILURE','SOURCE_UNAVAILABLE','QUERY_BUDGET_EXCEEDED','PAYLOAD_BUDGET_EXCEEDED','ARCHIVE_ROW_UNREADABLE'}

def connect_ro(path: Path):
    if not path.is_file():
        return None
    # Do not use immutable=1: it could miss committed WAL content.
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=0.20)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    return conn

def guard(conn, deadline, limit=20000):
    calls = [0]
    def progress():
        calls[0] += 1
        return 1 if calls[0] > limit or time.monotonic() >= deadline else 0
    conn.set_progress_handler(progress, 100)

def unguard(conn): conn.set_progress_handler(None, 0)

def verify(archive, source, spec, max_payload_bytes):
    """Pure in-memory contract. Never returns source identity, content, hash, or keys."""
    result = {'state':'ARCHIVE_ROW_UNREADABLE', 'byte_exact':False, 'replay_projection_equivalent':False}
    try:
        codec = archive['archive_codec']
        if codec != 'ZLIB_9':
            result['state']='ARCHIVE_DECODE_FAILURE';return result
        compressed = archive['archive_blob']
        if not isinstance(compressed, bytes) or len(compressed)>max_payload_bytes:
            result['state']='PAYLOAD_BUDGET_EXCEEDED';return result
        # bounded decompression, does not inflate a decompression bomb into memory
        d=zlib.decompressobj()
        raw=d.decompress(compressed,max_payload_bytes+1)
        if len(raw)>max_payload_bytes or d.unconsumed_tail:
            result['state']='PAYLOAD_BUDGET_EXCEEDED';return result
        raw+=d.flush(max_payload_bytes+1-len(raw))
        if len(raw)>max_payload_bytes or not d.eof or d.unused_data:
            result['state']='ARCHIVE_DECODE_FAILURE';return result
        if (hashlib.sha256(raw).hexdigest()!=archive['source_sha256'] or
            len(raw)!=archive['source_bytes'] or len(compressed)!=archive['archive_bytes']):
            result['state']='ARCHIVE_INTEGRITY_FAILURE';return result
        try: raw_text=raw.decode('utf-8')
        except UnicodeDecodeError:
            result['state']='PAYLOAD_INVALID_UTF8';return result
        if source is None:
            result['state']='SOURCE_MISSING';return result
        value=source['payload']
        if value is None:
            result['state']='SOURCE_NULL';return result
        original=value if isinstance(value,bytes) else value.encode('utf-8')
        if len(original)>max_payload_bytes:
            result['state']='PAYLOAD_BUDGET_EXCEEDED';return result
        if original!=raw:
            result['state']='SOURCE_BYTES_DIFFER';return result
        result['byte_exact']=True
        try:
            reconstructed=json.loads(raw_text)
            canonical=json.loads(original.decode('utf-8'))
        except (ValueError,UnicodeDecodeError):
            result['state']='JSON_PARSE_FAILURE';return result
        # Comparison is a bounded deterministic payload projection, not engine replay.
        if not isinstance(reconstructed,(dict,list)):
            result['state']='JSON_PARSE_FAILURE';return result
        fields=spec[4]
        result['replay_projection_equivalent']=(reconstructed==canonical and
            (not isinstance(canonical,dict) or all(reconstructed.get(k)==canonical.get(k) for k in fields)))
        result['state']='ARCHIVE_VERIFIED_SOURCE_EXACT'
        return result
    except (zlib.error, OverflowError, ValueError, TypeError, KeyError, MemoryError):
        result['state']='ARCHIVE_DECODE_FAILURE';return result

def run(root: Path, sample_rows=8, per_query_ms=400, total_ms=6000, max_payload_bytes=262144, max_total_payload_bytes=1048576):
    sample_rows=max(1,min(int(sample_rows),32))
    per_query_ms=max(20,min(int(per_query_ms),1000))
    total_ms=max(100,min(int(total_ms),15000))
    max_payload_bytes=max(1024,min(int(max_payload_bytes),1048576))
    max_total_payload_bytes=max(1024,min(int(max_total_payload_bytes),4194304))
    report={'schema':SCHEMA,'mode':'READ_ONLY_BOUNDED_PRODUCTION_PROBE','migration_authority':'BLOCKED_RESEARCH_ONLY',
            'production_reader_cutover':False,'production_replay_performed':False,
            'historical_replay_claim':'PAYLOAD_PROJECTION_ONLY_NOT_ENGINE_REPLAY',
            'limits':{'rows_per_payload_type':sample_rows,'per_query_ms':per_query_ms,'total_ms':total_ms,
                      'max_payload_bytes':max_payload_bytes,'global_payload_bytes':max_total_payload_bytes},
            'guardrails':{'production_db_open_mode':'ro','no_sqlite_writes':True,'no_schema_mutation':True,'no_checkpoint':True,
                          'no_vacuum':True,'no_delete':True,'no_payload_or_identifier_export':True,
                          'no_archival_persistence':True,'no_trade_execution_authority':True},'types':{}}
    deadline=time.monotonic()+total_ms/1000
    remaining=max_total_payload_bytes
    archive_path=root/'apex_historical_payload_archive.db'
    archive=None
    try:
        archive=connect_ro(archive_path)
        if archive is None:
            report['status']='BLOCKED_ARCHIVE_NOT_FOUND';return report
        for payload_type,spec in SPECS.items():
            result={'status':'NOT_STARTED','sampled':0,'state_counts':{},'byte_exact_matches':0,'replay_projection_matches':0,
                    'source_and_archive_correspondence_verified_exhaustively':False,'source_rows_total_unknown':True}
            report['types'][payload_type]=result
            if time.monotonic()>=deadline:
                result['status']='GLOBAL_BUDGET_EXCEEDED';continue
            source=None
            try:
                source=connect_ro(root/spec[0])
                if source is None:
                    result['status']='SOURCE_NOT_FOUND';continue
                guard(archive,min(deadline,time.monotonic()+per_query_ms/1000))
                try:
                    rows=archive.execute('''SELECT payload_type,row_id,source_table,source_column,
                      source_sha256,source_bytes,archive_codec,substr(archive_blob,1,?) AS archive_blob,archive_bytes
                      FROM historical_payload_archive WHERE payload_type=? ORDER BY rowid DESC LIMIT ?''',
                      (max_payload_bytes+1,payload_type,sample_rows)).fetchall()
                finally: unguard(archive)
                result['status']='SAMPLED' if rows else 'NO_ARCHIVE_SAMPLE'
                for a in rows:
                    if time.monotonic()>=deadline:
                        result['status']='GLOBAL_BUDGET_EXCEEDED';break
                    result['sampled']+=1
                    state='ARCHIVE_ROW_UNREADABLE';success=False;projection=False
                    if a['source_table']!=spec[1] or a['source_column']!=spec[3]:
                        state='ARCHIVE_METADATA_CONFLICT'
                    elif remaining<=0 or a['source_bytes']>max_payload_bytes or a['archive_bytes']>max_payload_bytes:
                        state='PAYLOAD_BUDGET_EXCEEDED'
                    else:
                        guard(source,min(deadline,time.monotonic()+per_query_ms/1000))
                        try:
                            sr=source.execute(f'SELECT substr(CAST("{spec[3]}" AS BLOB),1,?) AS payload FROM "{spec[1]}" WHERE "{spec[2]}"=? LIMIT 1',
                                              (max_payload_bytes+1,a['row_id'])).fetchone()
                        except sqlite3.OperationalError as ex:
                            state='QUERY_BUDGET_EXCEEDED' if 'interrupt' in str(ex).lower() else 'SOURCE_UNAVAILABLE'
                            sr=None
                        else:
                            # At most the audited payload limit is counted toward the budget.
                            remaining-=min(max(0,int(a['source_bytes'])),max_payload_bytes)
                            v=verify(a,sr,spec,max_payload_bytes)
                            state=v['state'];success=v['byte_exact'];projection=v['replay_projection_equivalent']
                        finally: unguard(source)
                    result['state_counts'][state]=result['state_counts'].get(state,0)+1
                    result['byte_exact_matches']+=int(success)
                    result['replay_projection_matches']+=int(projection)
            except sqlite3.Error as ex:
                result['status']='SQLITE_READ_UNAVAILABLE'
                result['error_type']=type(ex).__name__
            finally:
                if source is not None:source.close()
        report['status']='SAMPLED_CORRESPONDENCE_ONLY_MIGRATION_BLOCKED'
        report['remaining_gates']=['production_replay_equivalence','cross_database_gamma_decision_identity',
            'reader_cutover_coverage','historical_exhaustive_correspondence','external_backup_restore',
            'isolated_restore_rollback','representative_performance','stage3b1_reader_utf8_failure_fix_verified']
        return report
    finally:
        if archive is not None: archive.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',default='/data');p.add_argument('--output',required=True)
    p.add_argument('--sample-rows',type=int,default=8);p.add_argument('--query-budget-ms',type=int,default=400)
    p.add_argument('--total-budget-ms',type=int,default=6000);p.add_argument('--max-payload-bytes',type=int,default=262144)
    p.add_argument('--raw-byte-budget',type=int,default=1048576)
    a=p.parse_args()
    output=Path(a.output).resolve();root=Path(a.root).resolve()
    if output==root or root in output.parents:
        p.error('report must be written outside SQLite data root')
    report=run(root,a.sample_rows,a.query_budget_ms,a.total_budget_ms,a.max_payload_bytes,a.raw_byte_budget)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(f'Stage 3B.2 report: {output} | migration={report["migration_authority"]} | status={report["status"]}')
if __name__=='__main__':main()

#!/usr/bin/env python3
"""APEX Stage 3B.2.1: opt-in, read-only archive budget attribution and recovery.

Checks archived payloads against source bytes with strict, explicit byte budgets.
All identities and payload bytes remain in-process; only aggregate states are exported.
Metadata preflight prevents oversized payload materialization. Not full engine replay.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sqlite3
import time
import zlib
from pathlib import Path

SCHEMA = 'apex.stage3b21_archive_payload_budget_recovery.v1'
SPECS = {
    'DECISION_SNAPSHOT': ('apex_evidence_pipeline.db','decisions','decision_id','snapshot_json',('canonical_gamma_snapshot_id','decision_id','ticker','direction','action')),
    'TRIGGER_EVIDENCE': ('apex_trigger_observatory.db','observed_trade_triggers','trigger_id','evidence_json',('decision_id','canonical_gamma_snapshot_id','trigger_id','direction','symbol')),
}
# Per-record budgets limit compressed, inflated and canonical content separately.
# Global budget charges all three byte representations before materializing records.
PHASES = ('archive_compressed','archive_uncompressed','source_canonical')

def connect_ro(path: Path):
    if not path.is_file(): return None
    con=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=0.20)
    con.row_factory=sqlite3.Row
    con.execute('PRAGMA query_only=ON')
    return con

def guard(con, deadline, progress_limit=20000):
    n=[0]
    def progress():
        n[0]+=1
        return int(n[0]>progress_limit or time.monotonic()>=deadline)
    con.set_progress_handler(progress,100)

def unguard(con):con.set_progress_handler(None,0)

def bounded_query(con, sql, params, deadline, per_query_ms):
    if time.monotonic()>=deadline: return None,'GLOBAL_TIME_BUDGET_EXCEEDED'
    guard(con,min(deadline,time.monotonic()+per_query_ms/1000))
    try:return con.execute(sql,params).fetchone(),None
    except sqlite3.OperationalError as ex:
        return None,'QUERY_BUDGET_EXCEEDED' if 'interrupt' in str(ex).lower() else 'SQLITE_READ_UNAVAILABLE'
    except sqlite3.DatabaseError:return None,'SQLITE_READ_UNAVAILABLE'
    finally:unguard(con)

def _decompress_bounded(blob:bytes, cap:int):
    try:
        decompressor=zlib.decompressobj()
        raw=decompressor.decompress(blob,cap+1)
        if len(raw)>cap or decompressor.unconsumed_tail:return None,'ACTUAL_UNCOMPRESSED_LIMIT_EXCEEDED'
        raw+=decompressor.flush(cap+1-len(raw))
        if len(raw)>cap:return None,'ACTUAL_UNCOMPRESSED_LIMIT_EXCEEDED'
        if not decompressor.eof or decompressor.unused_data:return None,'ARCHIVE_DECODE_FAILURE'
        return raw,None
    except (zlib.error,ValueError,OverflowError,MemoryError):return None,'ARCHIVE_DECODE_FAILURE'

def _metadata_preflight(a, per_record_limit, remaining):
    """No blob or source payload has been materialized at this point."""
    try:
        compressed=int(a['archive_bytes']);raw=int(a['source_bytes'])
    except (ValueError,TypeError,OverflowError):return 'ARCHIVE_METADATA_INVALID',0
    if compressed<0 or raw<0:return 'ARCHIVE_METADATA_INVALID',0
    if compressed>per_record_limit:return 'ARCHIVE_COMPRESSED_LIMIT_EXCEEDED',0
    if raw>per_record_limit:return 'ARCHIVE_UNCOMPRESSED_LIMIT_EXCEEDED',0
    # Charge archive BLOB read + inflated bytes + canonical source bytes.
    estimated_cost=compressed+raw+raw
    if estimated_cost>remaining:return 'GLOBAL_RAW_BYTE_BUDGET_EXHAUSTED',estimated_cost
    return None,estimated_cost

def compare(a, source, max_payload_bytes):
    """Pure bounded payload check; no value, identifier or digest escapes."""
    if a['archive_codec']!='ZLIB_9':return 'ARCHIVE_DECODE_FAILURE',False,False
    blob=a['archive_blob']
    if not isinstance(blob,bytes):return 'ARCHIVE_ROW_UNREADABLE',False,False
    if len(blob)>max_payload_bytes:return 'ACTUAL_COMPRESSED_LIMIT_EXCEEDED',False,False
    raw,state=_decompress_bounded(blob,max_payload_bytes)
    if state:return state,False,False
    if (len(blob)!=a['archive_bytes'] or len(raw)!=a['source_bytes'] or
        hashlib.sha256(raw).hexdigest()!=a['source_sha256']):
        return 'ARCHIVE_INTEGRITY_FAILURE',False,False
    try:decoded=raw.decode('utf-8')
    except UnicodeDecodeError:return 'PAYLOAD_INVALID_UTF8',False,False
    if source is None:return 'SOURCE_MISSING',False,False
    value=source['payload']
    if value is None:return 'SOURCE_NULL',False,False
    canonical=value if isinstance(value,bytes) else value.encode('utf-8')
    if len(canonical)>max_payload_bytes:return 'ACTUAL_SOURCE_LIMIT_EXCEEDED',False,False
    if canonical!=raw:return 'SOURCE_BYTES_DIFFER',False,False
    try:
        obj=json.loads(decoded)
        replay=json.loads(canonical.decode('utf-8'))
    except (ValueError,UnicodeDecodeError):return 'JSON_PARSE_FAILURE',True,False
    if not isinstance(obj,(dict,list)):return 'JSON_PARSE_FAILURE',True,False
    return 'ARCHIVE_VERIFIED_SOURCE_EXACT',True,obj==replay

def _count(result,state):
    result['state_counts'][state]=result['state_counts'].get(state,0)+1

def run(root:Path,sample_rows=8,per_query_ms=400,total_ms=6000,
        max_payload_bytes=262144,max_total_payload_bytes=1048576):
    sample_rows=max(1,min(int(sample_rows),32))
    per_query_ms=max(20,min(int(per_query_ms),1000))
    total_ms=max(100,min(int(total_ms),15000))
    max_payload_bytes=max(1024,min(int(max_payload_bytes),1048576))
    max_total_payload_bytes=max(1024,min(int(max_total_payload_bytes),4194304))
    report={'schema':SCHEMA,'mode':'READ_ONLY_BOUNDED_PRODUCTION_PROBE',
      'migration_authority':'BLOCKED_RESEARCH_ONLY','production_reader_cutover':False,
      'production_replay_performed':False,'historical_replay_claim':'PAYLOAD_PROJECTION_ONLY_NOT_ENGINE_REPLAY',
      'limits':{'rows_per_payload_type':sample_rows,'per_query_ms':per_query_ms,'total_ms':total_ms,
                'max_payload_bytes':max_payload_bytes,'global_payload_bytes':max_total_payload_bytes,
                'byte_accounting':'archive_compressed_plus_archive_uncompressed_plus_source_canonical'},
      'guardrails':{'production_db_open_mode':'ro','no_sqlite_writes':True,'no_schema_mutation':True,
        'no_checkpoint':True,'no_vacuum':True,'no_delete':True,'no_payload_or_identifier_export':True,
        'no_archival_persistence':True,'no_trade_execution_authority':True},'types':{},
      'budget_attribution':{'estimated_bytes_charged':0,'remaining_bytes':max_total_payload_bytes,
       'compressed_bytes_charged':0,'uncompressed_bytes_charged':0,'source_bytes_charged':0,
       'charge_policy':'reserved_from_trusted_metadata_before_fetch;not_physical_disk_or_memory_usage'},
      'remaining_gates':['production_replay_equivalence','cross_database_gamma_decision_identity',
       'reader_cutover_coverage','historical_exhaustive_correspondence','external_backup_restore',
       'isolated_restore_rollback','representative_performance','stage3b1_reader_utf8_failure_fix_verified']}
    deadline=time.monotonic()+total_ms/1000
    remaining=max_total_payload_bytes
    archive=connect_ro(root/'apex_historical_payload_archive.db')
    globally_exhausted=False
    if archive is None:
        report['status']='BLOCKED_ARCHIVE_NOT_FOUND';return report
    try:
        for kind,spec in SPECS.items():
            r={'status':'NOT_STARTED','sampled':0,'evaluated':0,'state_counts':{},
               'byte_exact_matches':0,'replay_projection_matches':0,'metadata_preflight_skips':0,
               'source_and_archive_correspondence_verified_exhaustively':False,'source_rows_total_unknown':True}
            report['types'][kind]=r
            if globally_exhausted:
                r['status']='NOT_ATTEMPTED_GLOBAL_RAW_BYTE_BUDGET_EXHAUSTED';continue
            if time.monotonic()>=deadline:
                r['status']='GLOBAL_TIME_BUDGET_EXCEEDED';continue
            source=connect_ro(root/spec[0])
            if source is None:
                r['status']='SOURCE_NOT_FOUND';continue
            try:
                # Metadata only. Read BLOB and source contents one-at-a-time after budget preflight.
                guard(archive,min(deadline,time.monotonic()+per_query_ms/1000))
                try:
                    metadata=archive.execute('''SELECT rowid AS audit_rowid,payload_type,row_id,source_table,
                      source_column,source_sha256,source_bytes,archive_codec,archive_bytes
                      FROM historical_payload_archive WHERE payload_type=? ORDER BY rowid DESC LIMIT ?''',
                      (kind,sample_rows)).fetchall()
                except sqlite3.OperationalError as ex:
                    r['status']='QUERY_BUDGET_EXCEEDED' if 'interrupt' in str(ex).lower() else 'SQLITE_READ_UNAVAILABLE'
                    continue
                finally:unguard(archive)
                r['status']='SAMPLED' if metadata else 'NO_ARCHIVE_SAMPLE'
                for meta in metadata:
                    if time.monotonic()>=deadline:
                        r['status']='GLOBAL_TIME_BUDGET_EXCEEDED';break
                    r['sampled']+=1
                    if meta['source_table']!=spec[1] or meta['source_column']!=spec[3]:
                        _count(r,'ARCHIVE_METADATA_CONFLICT');continue
                    if meta['archive_codec']!='ZLIB_9':
                        _count(r,'ARCHIVE_DECODE_FAILURE');continue
                    state,cost=_metadata_preflight(meta,max_payload_bytes,remaining)
                    if state:
                        _count(r,state);r['metadata_preflight_skips']+=1
                        if state=='GLOBAL_RAW_BYTE_BUDGET_EXHAUSTED':
                            r['status']='GLOBAL_RAW_BYTE_BUDGET_EXHAUSTED'
                            globally_exhausted=True
                            break  # halt subsequent records and types until an operator selects another budget
                        continue  # oversize record does not prevent a smaller subsequent one
                    # Reserve full budget before fetching bytes. Subsequent failures still charge it.
                    c=int(meta['archive_bytes']);u=int(meta['source_bytes'])
                    remaining-=cost
                    b=report['budget_attribution']
                    b['compressed_bytes_charged']+=c;b['uncompressed_bytes_charged']+=u
                    b['source_bytes_charged']+=u;b['estimated_bytes_charged']+=cost
                    b['remaining_bytes']=remaining
                    a,err=bounded_query(archive,
                      'SELECT archive_codec,substr(archive_blob,1,?) AS archive_blob,source_sha256,source_bytes,archive_bytes FROM historical_payload_archive WHERE rowid=?',
                      (max_payload_bytes+1,meta['audit_rowid']),deadline,per_query_ms)
                    if err:_count(r,err);continue
                    if a is None:_count(r,'ARCHIVE_ROW_UNREADABLE');continue
                    # Source length first to attribute source growth and cap actual content fetch.
                    source_length,err=bounded_query(source,
                      f'SELECT length(CAST("{spec[3]}" AS BLOB)) AS source_length FROM "{spec[1]}" WHERE "{spec[2]}"=? LIMIT 1',
                      (meta['row_id'],),deadline,per_query_ms)
                    if err:_count(r,err);continue
                    if source_length is not None and source_length['source_length'] is not None and source_length['source_length']>max_payload_bytes:
                        _count(r,'ACTUAL_SOURCE_LIMIT_EXCEEDED');continue
                    sr,err=bounded_query(source,
                      f'SELECT substr(CAST("{spec[3]}" AS BLOB),1,?) AS payload FROM "{spec[1]}" WHERE "{spec[2]}"=? LIMIT 1',
                      (max_payload_bytes+1,meta['row_id']),deadline,per_query_ms)
                    if err:_count(r,err);continue
                    # A concurrently changed archive row is detected, not treated as matching.
                    if (a['source_sha256']!=meta['source_sha256'] or
                        a['source_bytes']!=meta['source_bytes'] or a['archive_bytes']!=meta['archive_bytes']):
                        _count(r,'ARCHIVE_METADATA_CHANGED_DURING_AUDIT');continue
                    state,exact,projection=compare(a,sr,max_payload_bytes)
                    _count(r,state);r['evaluated']+=1
                    r['byte_exact_matches']+=int(exact)
                    r['replay_projection_matches']+=int(projection)
            except sqlite3.DatabaseError as ex:
                r['status']='SQLITE_READ_UNAVAILABLE';r['error_type']=type(ex).__name__
            finally:source.close()
        report['status']='BOUNDED_CORRESPONDENCE_ATTRIBUTED_MIGRATION_BLOCKED'
        return report
    finally:archive.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',default='/data');p.add_argument('--output',required=True)
    p.add_argument('--sample-rows',type=int,default=8);p.add_argument('--query-budget-ms',type=int,default=400)
    p.add_argument('--total-budget-ms',type=int,default=6000)
    p.add_argument('--max-payload-bytes',type=int,default=262144)
    p.add_argument('--raw-byte-budget',type=int,default=1048576)
    a=p.parse_args();root=Path(a.root).resolve();output=Path(a.output).resolve()
    if output==root or root in output.parents:p.error('output must be outside SQLite data root')
    report=run(root,a.sample_rows,a.query_budget_ms,a.total_budget_ms,a.max_payload_bytes,a.raw_byte_budget)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    print(f'Stage 3B.2.1 report: {output} | migration={report["migration_authority"]} | status={report["status"]}')
if __name__=='__main__':main()

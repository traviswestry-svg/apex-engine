#!/usr/bin/env python3
"""APEX Stage 3B.3 — bounded, read-only reader/identity compatibility probe.

No production mutation, reader cutover, historical engine replay or archive migration.
Only aggregate classifications leave the process. Source reader inventory is static hints.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sqlite3
import time
import zlib
from pathlib import Path

SCHEMA = 'apex.stage3b3_canonical_reader_cross_database_identity.v1'
SPECS = {
    'DECISION_SNAPSHOT': ('apex_evidence_pipeline.db','decisions','decision_id','snapshot_json','observed_at'),
    'TRIGGER_EVIDENCE': ('apex_trigger_observatory.db','observed_trade_triggers','trigger_id','evidence_json','triggered_at'),
}
MAX_PER_RECORD = 1572864
MAX_GLOBAL = 16777216
MAX_SAMPLES = 4
MAX_FILES = 450
READER_HINTS = {
  'DECISION_SNAPSHOT': ('snapshot_json','decisions','retrieve_archived_payload'),
  'TRIGGER_EVIDENCE': ('evidence_json','observed_trade_triggers','retrieve_archived_payload'),
  'GAMMA_IDENTITY': ('canonical_gamma_snapshot_id','gamma_observational_snapshots'),
}

def incr(mapping, label): mapping[label] = mapping.get(label, 0) + 1

def ro(path):
    if not path.is_file(): return None
    c=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.2)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA query_only=ON')
    return c

def query(c, sql, args, deadline, query_ms, all_rows=False):
    if time.monotonic() >= deadline: return None,'GLOBAL_TIME_BUDGET_EXCEEDED'
    until=min(deadline,time.monotonic()+query_ms/1000)
    count=[0]
    def progress():
        count[0]+=1
        return int(count[0]>20000 or time.monotonic()>until)
    c.set_progress_handler(progress,100)
    try:
        cur=c.execute(sql,args)
        return (cur.fetchall() if all_rows else cur.fetchone()),None
    except sqlite3.Error as e:
        return None,'QUERY_INTERRUPTED' if 'interrupt' in str(e).lower() else 'QUERY_UNAVAILABLE'
    finally:
        c.set_progress_handler(None,0)

def indexed(c,table,key,deadline,ms):
    # Only fixed, audited table/column names are ever passed in.
    rows,err=query(c,f'EXPLAIN QUERY PLAN SELECT "{key}" FROM "{table}" WHERE "{key}"=? LIMIT 1',('!APEX_NO_MATCH!',),deadline,ms,True)
    if err or not rows: return False
    plan=' '.join(str(x[3]).upper() for x in rows)
    return 'SEARCH ' in plan and 'SCAN ' not in plan

def checked_inflate(blob, raw_len, cap):
    if not isinstance(blob,bytes) or len(blob)>cap: return None,'BLOB_UNAVAILABLE_OR_OVER_LIMIT'
    try:
        d=zlib.decompressobj()
        raw=d.decompress(blob,cap+1)
        if len(raw)>cap or d.unconsumed_tail: return None,'INFLATE_LIMIT_EXCEEDED'
        raw+=d.flush(cap+1-len(raw))
        if len(raw)>cap: return None,'INFLATE_LIMIT_EXCEEDED'
        if not d.eof or d.unused_data:return None,'ARCHIVE_DECODE_FAILURE'
        if len(raw)!=raw_len:return None,'DECLARED_LENGTH_MISMATCH'
        return raw,None
    except (zlib.error,ValueError,MemoryError,OverflowError):return None,'ARCHIVE_DECODE_FAILURE'

def compare_bytes(meta, archive, canonical, cap):
    if archive is None:return 'ARCHIVE_ROW_UNAVAILABLE'
    if archive['archive_codec']!='ZLIB_9':return 'UNSUPPORTED_CODEC'
    if not isinstance(archive['archive_blob'],bytes) or len(archive['archive_blob'])!=meta['archive_bytes']:
        return 'ARCHIVE_COMPRESSED_LENGTH_MISMATCH'
    raw,error=checked_inflate(archive['archive_blob'],int(meta['source_bytes']),cap)
    if error:return error
    if hashlib.sha256(raw).hexdigest()!=meta['source_sha256']:return 'ARCHIVE_HASH_MISMATCH'
    try:raw.decode('utf-8')
    except UnicodeDecodeError:return 'ARCHIVE_INVALID_UTF8_FAIL_CLOSED_REQUIRED'
    if canonical is None:return 'SOURCE_PAYLOAD_NULL'
    if isinstance(canonical,str):canonical=canonical.encode('utf-8')
    return 'ARCHIVE_SOURCE_BYTE_EXACT' if raw==canonical else 'ARCHIVE_SOURCE_DIVERGED'

def reference_inventory(root):
    base=root/'engine'
    result={'scope':'STATIC_TEXT_HINTS_ONLY_NOT_CALL_GRAPH','scanned':0,'max_files':MAX_FILES,
            'truncated':False,'categories':{}}
    files=sorted(base.rglob('*.py')) if base.is_dir() else []
    result['truncated']=len(files)>MAX_FILES
    files=files[:MAX_FILES]
    counts={kind:{'inline_read_hints':0,'archive_reader_hints':0,'both_in_same_file':0}
            for kind in READER_HINTS}
    for p in files:
        if p.is_symlink():continue
        try:
            if p.stat().st_size>1024*1024:continue
            s=p.read_text(encoding='utf-8',errors='replace')
        except OSError:continue
        result['scanned']+=1
        for k,terms in READER_HINTS.items():
            inline=all(t in s for t in terms[:-1]) if len(terms)>2 else all(t in s for t in terms)
            archive='retrieve_archived_payload' in s
            if inline:counts[k]['inline_read_hints']+=1
            if archive:counts[k]['archive_reader_hints']+=1
            if inline and archive:counts[k]['both_in_same_file']+=1
    result['categories']=counts
    return result

def run(root, repo_root=None, samples=2,query_ms=400,total_ms=10000,cap=MAX_PER_RECORD,budget=MAX_GLOBAL):
    samples=max(1,min(int(samples),MAX_SAMPLES))
    query_ms=max(20,min(int(query_ms),1000))
    total_ms=max(100,min(int(total_ms),20000))
    cap=max(1024,min(int(cap),MAX_PER_RECORD))
    budget=max(1024,min(int(budget),MAX_GLOBAL))
    deadline=time.monotonic()+total_ms/1000
    report={'schema':SCHEMA,'mode':'READ_ONLY_BOUNDED_RESEARCH','migration_authority':'BLOCKED_RESEARCH_ONLY',
        'production_reader_cutover':False,'production_engine_replay_performed':False,
        'guardrails':{'sqlite_mode':'ro','no_sqlite_writes':True,'no_archive_mutation':True,
                      'no_deletion':True,'no_checkpoint':True,'no_vacuum':True,
                      'no_payloads_hashes_or_ids_exported':True,'no_trade_execution_authority':True,
                      'requires_indexed_identity_lookups':True,'cooperative_query_deadlines_not_hard_io_limit':True},
        'limits':{'per_edge_per_type':samples,'per_record_bytes':cap,'shared_byte_reservations':budget,
                  'query_budget_ms':query_ms,'total_budget_ms':total_ms},
        'budget':{'reserved_bytes':0,'remaining_bytes':budget},
        'types':{},'cross_database_identity':{},
        'reader_contract':{'stage3b1_invalid_utf8_production_patch_verified':False,
                           'actual_reader_cutover_tested':False,
                           'archive_and_inline_byte_equivalence_is_not_reader_cutover_equivalence':True},
        'remaining_gates':['stage3b1_reader_fix_verified','all_reader_cutover_coverage','production_engine_replay_equivalence',
         'population_wide_archive_correspondence','external_backup_restore','isolated_copy_rollback',
         'representative_performance','cross_database_identity_population_coverage']}
    if repo_root is not None:report['reader_inventory']=reference_inventory(repo_root)
    arc=ro(root/'apex_historical_payload_archive.db')
    if arc is None:
        report['status']='ARCHIVE_DATABASE_NOT_FOUND';return report
    gamma=ro(root/'apex_tracking.db')
    decisions=ro(root/'apex_evidence_pipeline.db')
    gamma_index=gamma is not None and indexed(gamma,'gamma_observational_snapshots','canonical_gamma_snapshot_id',deadline,query_ms)
    decision_index=decisions is not None and indexed(decisions,'decisions','decision_id',deadline,query_ms)
    report['cross_database_identity']={'gamma_index_verified':bool(gamma_index),
        'decision_index_verified':bool(decision_index),'states':{},'links_evaluated':0,
        'sampled_only':True,'null_ids_not_treated_as_mismatches':True}
    try:
        for kind,(filename,table,key,column,time_column) in SPECS.items():
            out={'sampled':0,'evaluated':0,'exact_matches':0,'states':{},'source_index_verified':False,
                 'cohort':'OLDEST_AND_NEWEST','representative':False,'status':'NOT_STARTED'}
            report['types'][kind]=out
            src=ro(root/filename)
            if src is None:out['status']='SOURCE_DB_NOT_FOUND';continue
            try:
                if not indexed(src,table,key,deadline,query_ms):out['status']='SOURCE_ID_INDEX_UNVERIFIED';continue
                out['source_index_verified']=True
                archive_meta='''SELECT rowid AS audit_rowid,payload_type,row_id,source_table,source_column,
                    observed_at,source_sha256,source_bytes,archive_codec,archive_bytes
                    FROM historical_payload_archive WHERE payload_type=? ORDER BY rowid {direction} LIMIT ?'''
                metas=[];seen=set()
                for direction in ('ASC','DESC'):
                    rows,err=query(arc,archive_meta.format(direction=direction),(kind,samples),deadline,query_ms,True)
                    if err:incr(out['states'],err);continue
                    for m in rows:
                        if m['audit_rowid'] not in seen:
                            seen.add(m['audit_rowid']);metas.append(m)
                out['status']='SAMPLED' if metas else 'NO_ARCHIVE_ROWS_OR_QUERY_LIMIT'
                for meta in metas:
                    out['sampled']+=1
                    if meta['source_table']!=table or meta['source_column']!=column:
                        incr(out['states'],'ARCHIVE_SOURCE_MAPPING_CONFLICT');continue
                    source_row,err=query(src,f'SELECT "{time_column}" AS source_time, '
                        + ('canonical_gamma_snapshot_id,decision_id,symbol AS source_ticker,' if kind=='TRIGGER_EVIDENCE' else 'canonical_gamma_snapshot_id,ticker AS source_ticker,')
                        + f'length(CAST("{column}" AS BLOB)) AS payload_bytes '
                        +f'FROM "{table}" WHERE "{key}"=? LIMIT 1',(meta['row_id'],),deadline,query_ms)
                    if err:incr(out['states'],err);continue
                    if source_row is None:incr(out['states'],'SOURCE_ROW_MISSING');continue
                    if source_row['source_time']!=meta['observed_at']:
                        incr(out['states'],'SOURCE_TIME_MISMATCH');continue
                    # Independent link validation; link equality is never confused with payload correspondence.
                    cid=source_row['canonical_gamma_snapshot_id']
                    links=report['cross_database_identity']
                    if not cid:incr(links['states'],'GAMMA_ID_NULL_OR_UNLINKED')
                    elif not gamma_index:incr(links['states'],'GAMMA_LOOKUP_INDEX_UNVERIFIED')
                    else:
                        g,err=query(gamma,'SELECT canonical_gamma_snapshot_id,ticker FROM gamma_observational_snapshots '
                            'WHERE canonical_gamma_snapshot_id=? LIMIT 1',(cid,),deadline,query_ms)
                        if err:incr(links['states'],err)
                        elif g is None:incr(links['states'],'GAMMA_ID_NOT_FOUND')
                        else:
                            links['links_evaluated']+=1
                            incr(links['states'],'GAMMA_ID_FOUND_TICKER_AGREES' if g['ticker']==source_row['source_ticker'] else 'GAMMA_ID_FOUND_TICKER_CONFLICT')
                    if kind=='TRIGGER_EVIDENCE':
                        did=source_row['decision_id']
                        if not did:incr(links['states'],'TRIGGER_DECISION_ID_NULL')
                        elif not decision_index:incr(links['states'],'DECISION_LOOKUP_INDEX_UNVERIFIED')
                        else:
                            d,err=query(decisions,'SELECT canonical_gamma_snapshot_id FROM decisions WHERE decision_id=? LIMIT 1',(did,),deadline,query_ms)
                            if err:incr(links['states'],err)
                            elif d is None:incr(links['states'],'TRIGGER_DECISION_NOT_FOUND')
                            else:
                                incr(links['states'],'TRIGGER_DECISION_FOUND');links['links_evaluated']+=1
                                if cid and d['canonical_gamma_snapshot_id'] and d['canonical_gamma_snapshot_id']!=cid:
                                    incr(links['states'],'TRIGGER_DECISION_GAMMA_ID_CONFLICT')
                                elif cid and d['canonical_gamma_snapshot_id']==cid:
                                    incr(links['states'],'TRIGGER_DECISION_GAMMA_ID_AGREES')
                                else:incr(links['states'],'TRIGGER_DECISION_GAMMA_LINK_INCOMPLETE')
                    raw_len=meta['source_bytes'];zip_len=meta['archive_bytes']
                    if not isinstance(raw_len,int) or not isinstance(zip_len,int) or min(raw_len,zip_len)<0:
                        incr(out['states'],'INVALID_SIZE_METADATA');continue
                    if max(raw_len,zip_len)>cap or (source_row['payload_bytes'] or 0)>cap:
                        incr(out['states'],'PER_RECORD_CAP_EXCEEDED');continue
                    charge=2*raw_len+zip_len
                    if charge>report['budget']['remaining_bytes']:
                        incr(out['states'],'GLOBAL_BYTE_BUDGET_EXCEEDED');break
                    report['budget']['remaining_bytes']-=charge;report['budget']['reserved_bytes']+=charge
                    archive,err=query(arc,'SELECT archive_blob,archive_codec FROM historical_payload_archive WHERE rowid=?',(meta['audit_rowid'],),deadline,query_ms)
                    if err:incr(out['states'],err);continue
                    raw,err=query(src,f'SELECT CAST("{column}" AS BLOB) AS payload FROM "{table}" WHERE "{key}"=? LIMIT 1',(meta['row_id'],),deadline,query_ms)
                    if err:incr(out['states'],err);continue
                    state=compare_bytes(meta,archive,None if raw is None else raw['payload'],cap)
                    incr(out['states'],state);out['evaluated']+=1
                    if state=='ARCHIVE_SOURCE_BYTE_EXACT':out['exact_matches']+=1
            finally:src.close()
        report['status']='BOUNDED_READER_IDENTITY_EVIDENCE_MIGRATION_BLOCKED'
        return report
    finally:
        arc.close()
        if gamma:gamma.close()
        if decisions:decisions.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',default='/data');p.add_argument('--repo-root',default='.')
    p.add_argument('--output',required=True);p.add_argument('--sample-rows',type=int,default=2)
    p.add_argument('--query-budget-ms',type=int,default=400);p.add_argument('--total-budget-ms',type=int,default=10000)
    p.add_argument('--max-payload-bytes',type=int,default=1572864);p.add_argument('--raw-byte-budget',type=int,default=16777216)
    a=p.parse_args();root=Path(a.root).resolve();output=Path(a.output).resolve()
    if output==root or root in output.parents:p.error('output must be outside database root')
    report=run(root,Path(a.repo_root).resolve(),a.sample_rows,a.query_budget_ms,a.total_budget_ms,a.max_payload_bytes,a.raw_byte_budget)
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print('Stage 3B.3 report:',output,'| migration='+report['migration_authority'],'| status='+report['status'])
if __name__=='__main__':main()

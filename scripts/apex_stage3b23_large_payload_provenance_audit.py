#!/usr/bin/env python3
"""APEX Stage 3B.2.3 — bounded, read-only large archive comparison.

Examines a tiny recent/old archive cohort and compares decompressed exact bytes
with indexed canonical source rows. Reports aggregate statuses and JSON shape only.
NOT production replay, archive promotion, retention authorization or migration.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sqlite3
import time
import zlib
from pathlib import Path

SCHEMA='apex.stage3b23_large_payload_provenance_audit.v1'
SPECS={
 'DECISION_SNAPSHOT':('apex_evidence_pipeline.db','decisions','decision_id','snapshot_json','observed_at'),
 'TRIGGER_EVIDENCE':('apex_trigger_observatory.db','observed_trade_triggers','trigger_id','evidence_json','triggered_at'),
}
MAX_CAP=1572864
MAX_GLOBAL=16777216
META='''SELECT rowid AS probe_rowid,payload_type,row_id,source_table,source_column,observed_at,
 source_sha256,source_bytes,archive_codec,archive_bytes,apex_version,schema_version,integrity_status
 FROM historical_payload_archive WHERE payload_type=? ORDER BY rowid {order} LIMIT ?'''

def ro(path):
 if not path.is_file():return None
 con=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.2)
 con.row_factory=sqlite3.Row
 con.execute('PRAGMA query_only=ON')
 return con

def bounded(con,sql,params,deadline,query_ms,many=False):
 if time.monotonic()>=deadline:return None,'GLOBAL_TIME_BUDGET_EXCEEDED'
 stop=min(deadline,time.monotonic()+query_ms/1000)
 calls=[0]
 def tick():
  calls[0]+=1
  return int(calls[0]>20000 or time.monotonic()>=stop)
 con.set_progress_handler(tick,100)
 try:
  cur=con.execute(sql,params)
  return (cur.fetchall() if many else cur.fetchone()),None
 except sqlite3.Error as exc:
  return None,'QUERY_BUDGET_EXCEEDED' if 'interrupt' in str(exc).lower() else 'SQLITE_READ_UNAVAILABLE'
 finally:con.set_progress_handler(None,0)

def indexed(con,table,key,deadline,query_ms):
 rows,err=bounded(con,f'EXPLAIN QUERY PLAN SELECT "{key}" FROM "{table}" WHERE "{key}"=? LIMIT 1',('__APEX_IMPOSSIBLE__',),deadline,query_ms,True)
 if err or not rows:return False
 detail=' '.join(str(r[3]).upper() for r in rows)
 return 'SEARCH ' in detail and 'SCAN ' not in detail

def inflate(blob,expected,cap):
 """Bound inflation even if malicious metadata understates the actual output."""
 if not isinstance(blob,bytes):return None,'ARCHIVE_BLOB_UNAVAILABLE'
 if len(blob)>cap:return None,'COMPRESSED_SIZE_LIMIT_EXCEEDED'
 try:
  dec=zlib.decompressobj()
  raw=dec.decompress(blob,cap+1)
  if len(raw)>cap or dec.unconsumed_tail:return None,'ACTUAL_INFLATED_LIMIT_EXCEEDED'
  raw+=dec.flush(cap+1-len(raw))
  if len(raw)>cap:return None,'ACTUAL_INFLATED_LIMIT_EXCEEDED'
  if not dec.eof or dec.unused_data:return None,'ARCHIVE_DECODE_FAILURE'
  if len(raw)!=expected:return None,'ARCHIVE_DECLARED_LENGTH_MISMATCH'
  return raw,None
 except (zlib.error,ValueError,OverflowError,MemoryError):return None,'ARCHIVE_DECODE_FAILURE'

def shape(raw):
 """No keys, values, hashes, or IDs leave this function."""
 try:value=json.loads(raw.decode('utf-8'))
 except (UnicodeError,ValueError):return 'INVALID_JSON_OR_UTF8',None
 if isinstance(value,dict):return 'OBJECT',len(value)
 if isinstance(value,list):return 'ARRAY',len(value)
 return 'SCALAR',None

def safe_version(v):
 import re
 return v if isinstance(v,str) and re.fullmatch('[a-zA-Z0-9_.-]{1,32}',v) else 'OTHER_OR_MISSING'

def tally(counts,key):counts[key]=counts.get(key,0)+1

def check(meta,archive_row,source_row,cap):
 """Pure function; accepts SQLite Rows or ordinary dicts; no data emitted."""
 if archive_row is None:return 'ARCHIVE_RECORD_MISSING',False,False,None
 blob=archive_row['archive_blob']
 if not isinstance(blob,bytes) or len(blob)!=meta['archive_bytes']:
  return 'ARCHIVE_COMPRESSED_LENGTH_MISMATCH',False,False,None
 raw,error=inflate(blob,int(meta['source_bytes']),cap)
 if error:return error,False,False,None
 if hashlib.sha256(raw).hexdigest()!=meta['source_sha256']:
  return 'ARCHIVE_SHA256_MISMATCH',False,False,None
 fmt,top_count=shape(raw)
 if source_row is None:return 'SOURCE_ROW_MISSING',False,False,fmt
 canonical=source_row['canonical']
 if canonical is None:return 'SOURCE_PAYLOAD_NULL',False,False,fmt
 if isinstance(canonical,str):canonical=canonical.encode('utf-8')
 if not isinstance(canonical,bytes):return 'SOURCE_PAYLOAD_INVALID_TYPE',False,False,fmt
 if len(canonical)>cap:return 'SOURCE_ACTUAL_LENGTH_EXCEEDS_CAP',False,False,fmt
 if canonical!=raw:return 'SOURCE_BYTES_DIFFER',False,False,fmt
 # Byte-exact match establishes projection equivalence only for valid JSON.
 return 'ARCHIVE_VERIFIED_SOURCE_EXACT',True,fmt in ('OBJECT','ARRAY'),fmt

def run(root:Path,sample_rows=2,query_ms=400,total_ms=10000,cap=1572864,budget=16777216):
 sample_rows=max(1,min(int(sample_rows),4))
 query_ms=max(20,min(int(query_ms),1000))
 total_ms=max(100,min(int(total_ms),20000))
 cap=max(1024,min(int(cap),MAX_CAP))
 budget=max(1024,min(int(budget),MAX_GLOBAL))
 deadline=time.monotonic()+total_ms/1000
 report={'schema':SCHEMA,'mode':'READ_ONLY_BOUNDED_PRODUCTION_PROBE',
  'migration_authority':'BLOCKED_RESEARCH_ONLY','production_reader_cutover':False,
  'production_engine_replay_performed':False,'historical_replay_claim':'PAYLOAD_PROJECTION_ONLY',
  'limits':{'samples_per_edge_per_type':sample_rows,'max_unique_per_type':2*sample_rows,
            'query_ms':query_ms,'total_ms':total_ms,'max_payload_bytes':cap,
            'global_reserved_byte_budget':budget,
            'accounting':'archive_compressed + archive_uncompressed + source_canonical reserved before fetch'},
  'budget':{'reserved_bytes':0,'remaining_bytes':budget,'reservations':0},
  'guardrails':{'production_sqlite_mode':'ro','no_sqlite_writes':True,'no_checkpoint':True,
   'no_vacuum':True,'no_delete':True,'no_migration':True,'no_payload_export':True,
   'no_identifiers_or_hashes_exported':True,'index_required_for_source_lookup':True,
   'bounded_inflation':True,'no_trade_or_execution_authority':True},
  'types':{},'remaining_gates':['historical_exhaustive_correspondence','production_engine_replay_equivalence',
    'cross_database_gamma_and_decision_identity','all_reader_cutover_coverage',
    'external_backup_restore','isolated_restored_copy_rollback',
    'stage3b1_utf8_reader_fix_verified','production_representative_performance']}
 archive=ro(root/'apex_historical_payload_archive.db')
 if archive is None:
  report['status']='ARCHIVE_DATABASE_NOT_FOUND';return report
 global_exhausted=False
 try:
  for kind,(filename,table,key,column,timestamp) in SPECS.items():
   r={'status':'NOT_STARTED','sampled':0,'evaluated':0,'byte_exact_matches':0,
      'payload_projection_matches':0,'states':{},'shape_types':{},'version_counts':{},
      'metadata_over_cap':0,'metadata_source_matches':0,'time_exact_matches':0,
      'source_rows_total_unknown':True,'representative_sample':False,
      'archive_integrity_verified_exhaustively':False}
   report['types'][kind]=r
   if global_exhausted:r['status']='NOT_ATTEMPTED_GLOBAL_BUDGET_EXHAUSTED';continue
   source=ro(root/filename)
   if source is None:r['status']='SOURCE_DATABASE_UNAVAILABLE';continue
   try:
    if not indexed(source,table,key,deadline,query_ms):
     r['status']='SOURCE_INDEX_NOT_VERIFIED';continue
    cohorts=[];seen=set()
    for order in ('ASC','DESC'):
     rows,err=bounded(archive,META.format(order=order),(kind,sample_rows),deadline,query_ms,True)
     if err:tally(r['states'],err);continue
     for meta in rows:
      if meta['probe_rowid'] not in seen:
       seen.add(meta['probe_rowid']);cohorts.append(meta)
    r['status']='SAMPLED' if cohorts else 'NO_ARCHIVE_ROWS_OR_QUERY_LIMIT'
    for m in cohorts:
     if time.monotonic()>=deadline:r['status']='GLOBAL_TIME_BUDGET_EXCEEDED';break
     r['sampled']+=1
     tally(r['version_counts'],safe_version(m['apex_version']))
     if m['payload_type']!=kind or m['source_table']!=table or m['source_column']!=column:
      tally(r['states'],'SOURCE_MAPPING_CONFLICT');continue
     r['metadata_source_matches']+=1
     a_bytes=m['archive_bytes'];raw_bytes=m['source_bytes']
     if type(a_bytes) is not int or type(raw_bytes) is not int or a_bytes<0 or raw_bytes<0:
      tally(r['states'],'INVALID_ARCHIVE_SIZE_METADATA');continue
     if a_bytes>cap or raw_bytes>cap:
      tally(r['states'],'ARCHIVE_METADATA_OVER_PER_RECORD_CAP');r['metadata_over_cap']+=1;continue
     reserve=a_bytes+raw_bytes*2
     if reserve>report['budget']['remaining_bytes']:
      tally(r['states'],'GLOBAL_BYTE_BUDGET_EXHAUSTED');r['status']='GLOBAL_BYTE_BUDGET_EXHAUSTED'
      global_exhausted=True;break
     report['budget']['reserved_bytes']+=reserve
     report['budget']['remaining_bytes']-=reserve
     report['budget']['reservations']+=1
     src,err=bounded(source,f'SELECT "{timestamp}" AS source_time, length(CAST("{column}" AS BLOB)) AS canonical_length FROM "{table}" WHERE "{key}"=? LIMIT 1',(m['row_id'],),deadline,query_ms)
     if err:tally(r['states'],err);continue
     if src is None:tally(r['states'],'SOURCE_ROW_MISSING');continue
     if src['source_time']==m['observed_at']:r['time_exact_matches']+=1
     else:
      tally(r['states'],'SOURCE_TIME_DIFFERENCE');continue
     if src['canonical_length'] is None:tally(r['states'],'SOURCE_PAYLOAD_NULL');continue
     if src['canonical_length']>cap:tally(r['states'],'SOURCE_LENGTH_OVER_CAP');continue
     arc,err=bounded(archive,'''SELECT archive_blob,source_sha256,source_bytes,archive_bytes,archive_codec
       FROM historical_payload_archive WHERE rowid=? LIMIT 1''',(m['probe_rowid'],),deadline,query_ms)
     if err:tally(r['states'],err);continue
     if arc is None:tally(r['states'],'ARCHIVE_RECORD_MISSING');continue
     if (arc['source_sha256']!=m['source_sha256'] or arc['source_bytes']!=m['source_bytes'] or
         arc['archive_bytes']!=m['archive_bytes'] or arc['archive_codec']!=m['archive_codec']):
      tally(r['states'],'METADATA_CHANGED_DURING_AUDIT');continue
     if arc['archive_codec']!='ZLIB_9':tally(r['states'],'UNSUPPORTED_CODEC');continue
     source_row,err=bounded(source,f'SELECT CAST("{column}" AS BLOB) AS canonical FROM "{table}" WHERE "{key}"=? LIMIT 1',(m['row_id'],),deadline,query_ms)
     if err:tally(r['states'],err);continue
     state,exact,project,fmt=check(m,arc,source_row,cap)
     tally(r['states'],state)
     if fmt:tally(r['shape_types'],fmt)
     r['evaluated']+=1
     r['byte_exact_matches']+=int(exact)
     r['payload_projection_matches']+=int(project)
   finally:source.close()
  report['status']='BOUNDED_LARGE_PAYLOAD_CORRESPONDENCE_MIGRATION_BLOCKED'
  return report
 finally:archive.close()

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--root',default='/data');p.add_argument('--output',required=True)
 p.add_argument('--sample-rows',type=int,default=2)
 p.add_argument('--query-budget-ms',type=int,default=400)
 p.add_argument('--total-budget-ms',type=int,default=10000)
 p.add_argument('--max-payload-bytes',type=int,default=1572864)
 p.add_argument('--raw-byte-budget',type=int,default=16777216)
 a=p.parse_args();root=Path(a.root).resolve();out=Path(a.output).resolve()
 if out==root or root in out.parents:p.error('output must be outside database root')
 result=run(root,a.sample_rows,a.query_budget_ms,a.total_budget_ms,a.max_payload_bytes,a.raw_byte_budget)
 out.parent.mkdir(parents=True,exist_ok=True)
 out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
 print(f'Stage 3B.2.3 report: {out} | migration={result["migration_authority"]} | status={result["status"]}')
if __name__=='__main__':main()

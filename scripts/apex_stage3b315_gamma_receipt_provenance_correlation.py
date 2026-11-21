#!/usr/bin/env python3
"""APEX 3B.3.15: bounded read-only stored gamma receipt/decision correlation.

Not a provider availability attestation, historical replay, producer attribution,
point-in-time snapshot, or production authorization. No raw identifiers or times
are emitted. Never changes original SQLite files.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from urllib.parse import quote

SCHEMA = 'apex.stage3b315_gamma_receipt_decision_provenance.v1'
PREV_SCHEMA = 'apex.stage3b314_evidence_source_inventory.v1'
DECISION_TABLE = 'decisions'
GAMMA_TABLE = 'gamma_observational_snapshots'
REFERENCE = '2026-09-18T13:45:00.256463Z'  # historical reference, NOT effective policy date
DECISION_TIME_COLUMNS = ('decision_time', 'created_at', 'timestamp')
GAMMA_KEY = 'canonical_gamma_snapshot_id'
SYMBOL_COLUMNS = ('symbol', 'underlying_symbol', 'ticker')
DB_SUFFIXES = ('.db', '.sqlite', '.sqlite3')

class AuditIssue(Exception):
    pass


def timestamp(value):
    """Require an explicit UTC offset; never infer timezone for naive strings."""
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, (float, int)):
            if not (0 <= float(value) <= 4102444800): return None
            return datetime.fromtimestamp(value, timezone.utc)
        if isinstance(value, str):
            s = value.strip()
            if not s: return None
            if s.endswith('Z'): s = s[:-1] + '+00:00'
            d = datetime.fromisoformat(s)
            return d.astimezone(timezone.utc) if d.tzinfo and d.utcoffset() is not None else None
    except (ValueError, OverflowError, OSError, TypeError):
        pass
    return None


def bound_path(path, root):
    p = Path(path)
    if p.is_symlink(): raise AuditIssue('SYMLINK_INPUT_REJECTED')
    real = p.resolve(strict=True)
    if real != root and root not in real.parents:
        raise AuditIssue('SOURCE_OUTSIDE_ROOT')
    if not real.is_file(): raise AuditIssue('SOURCE_NOT_FILE')
    return real


def connect(path):
    # URI ro and query_only: no CREATE/UPDATE, no journal writes required.
    uri = 'file:' + quote(str(path), safe='/') + '?mode=ro'
    db = sqlite3.connect(uri, uri=True, timeout=.2)
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA busy_timeout=200')
    return db


def table_columns(db, table):
    # Table strings are script constants, never interpolated from arbitrary input.
    found = db.execute('SELECT name FROM sqlite_master WHERE type="table" AND name=?', (table,)).fetchone()
    if not found: return set()
    return {row[1] for row in db.execute('PRAGMA table_info("' + table + '")')}


def has_index(db, table, column):
    for idx in db.execute('PRAGMA index_list("' + table + '")'):
        # A composite index is adequate only if exact-id column is leftmost.
        index_name = idx[1]
        if not isinstance(index_name, str) or '"' in index_name: continue
        cols = list(db.execute('PRAGMA index_info("' + index_name + '")'))
        if cols and cols[0][2] == column: return True
    return False


def detect(root, explicit, table, max_files, max_depth):
    if explicit:
        p = bound_path(explicit, root)
        with closing(connect(p)) as db:
            if not table_columns(db, table): raise AuditIssue('EXPLICIT_DATABASE_TABLE_MISSING')
        return p, 1
    candidates = []
    inspected = 0
    stack = [(root, 0)]
    while stack:
        folder, depth = stack.pop()
        for entry in sorted(folder.iterdir(), key=lambda x: x.name):
            if entry.is_symlink(): continue
            if entry.is_dir():
                if depth < max_depth: stack.append((entry, depth+1))
                continue
            if not entry.is_file() or entry.suffix.lower() not in DB_SUFFIXES: continue
            inspected += 1
            if inspected > max_files: raise AuditIssue('FILE_DISCOVERY_LIMIT_REACHED')
            try:
                with closing(connect(entry)) as db:
                    if table_columns(db, table): candidates.append(entry)
            except sqlite3.Error:
                continue
    if not candidates: raise AuditIssue('CANDIDATE_DATABASE_NOT_FOUND')
    if len(candidates) != 1: raise AuditIssue('AMBIGUOUS_DATABASE_CANDIDATES')
    return candidates[0], inspected


def previous_inventory(path):
    if not path: return 'NOT_SUPPLIED', None
    p = Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size > 2*1024*1024:
        return 'MISSING_OR_INVALID', None
    data = p.read_bytes()
    try: x=json.loads(data)
    except (ValueError, UnicodeError): return 'MISSING_OR_INVALID', None
    if (not isinstance(x, dict) or x.get('schema') != PREV_SCHEMA or
        x.get('status') != 'BOUNDED_INVENTORY_COMPLETED' or
        x.get('migration_authority') != 'BLOCKED_RESEARCH_ONLY'):
        return 'MISSING_OR_INVALID', None
    return 'READ_AND_SCHEMA_CHECKED', hashlib.sha256(data).hexdigest()


def base_report():
    return {
      'schema': SCHEMA,
      'status': 'UNVERIFIED',
      'mode': 'BOUNDED_READ_ONLY_EXACT_ID_RECEIPT_CORRELATION',
      'migration_authority':'BLOCKED_RESEARCH_ONLY',
      'guardrails':{
        'sqlite_mode':'ro', 'sqlite_query_only':True, 'no_writes_to_inputs':True,
        'no_record_or_identifier_export':True, 'no_raw_timestamps_export':True,
        'no_latest_gamma_substitution':True, 'no_backfill':True,
        'no_historical_reclassification':True, 'no_trade_execution':True,
        'no_runtime_execution':True, 'no_cutover':True},
      'sources':{'stage3b314':'NOT_SUPPLIED', 'decision_db':'NOT_INSPECTED', 'gamma_db':'NOT_INSPECTED'},
      'counts':{},
      'gates':{
        'schema_compatible':'UNVERIFIED', 'bounded_coverage':'UNVERIFIED',
        'exact_gamma_id_correlation':'UNVERIFIED',
        'stored_receipt_and_persistence_predecision':'UNVERIFIED',
        'decision_provenance_linkage':'UNVERIFIED',
        'producer_origin':'UNVERIFIED', 'provider_actual_availability':'UNVERIFIED',
        'runtime_gamma_activation':'UNVERIFIED', 'cross_database_snapshot_consistency':'UNVERIFIED',
        'full_historical_replay':'UNVERIFIED'},
      'limitations':[
        'Historical reference timestamp is a partition marker, not a policy-effective date.',
        'A stored receipt or persistence time is a first-party claim, not independently attested availability.',
        'SQLite files are read independently without a shared point-in-time transaction.',
        'Exact-ID correlation is not evidence of which producer executed the runtime gamma feature.',
        'Decision provenance snapshot_id is not assumed to be the canonical gamma snapshot ID.',
        'Schema availability does not establish historical row presence or independent source authenticity.'
      ]}


def audit(args):
    r = base_report()
    prev, digest = previous_inventory(args.stage3b314_report)
    r['sources']['stage3b314'] = prev
    if digest: r['stage3b314_sha256'] = digest
    if args.require_previous and prev != 'READ_AND_SCHEMA_CHECKED':
        r['status'] = 'PREREQUISITE_UNVERIFIED'; return r
    root = Path(args.root).resolve(strict=True)
    if not root.is_dir(): raise AuditIssue('ROOT_NOT_DIRECTORY')
    decpath, nd = detect(root, args.decision_db, DECISION_TABLE,args.max_files,args.max_depth)
    gammapath, ng = detect(root, args.gamma_db, GAMMA_TABLE,args.max_files,args.max_depth)
    r['sources'].update({'decision_db':'SQLITE_SCHEMA_AND_BOUNDED_ROWS_INSPECTED',
                         'gamma_db':'SQLITE_SCHEMA_AND_EXACT_ID_LOOKUPS_INSPECTED'})
    r['discovery'] = {'files_examined_for_decision':nd,'files_examined_for_gamma':ng}
    limit_deadline = time.monotonic() + args.budget_seconds
    def progress():
        return int(time.monotonic() >= limit_deadline)
    with closing(connect(decpath)) as dd, closing(connect(gammapath)) as gg:
        dd.set_progress_handler(progress,1000)
        gg.set_progress_handler(progress,1000)
        dc = table_columns(dd, DECISION_TABLE); gc = table_columns(gg,GAMMA_TABLE)
        dtime = next((x for x in DECISION_TIME_COLUMNS if x in dc),None)
        dsymbol = next((x for x in SYMBOL_COLUMNS if x in dc),None)
        gsymbol = next((x for x in SYMBOL_COLUMNS if x in gc),None)
        required_dc = {'decision_id', GAMMA_KEY}
        required_gc = {GAMMA_KEY,'received_at','persisted_at'}
        if not dtime or not required_dc.issubset(dc) or not required_gc.issubset(gc):
            r['status']='SCHEMA_INCOMPATIBLE_FAIL_CLOSED';return r
        if not has_index(gg,GAMMA_TABLE,GAMMA_KEY):
            r['status']='GAMMA_EXACT_ID_UNINDEXED_FAIL_CLOSED';return r
        r['gates']['schema_compatible']='PASS'
        r['schema_capabilities']={
          'decision_symbol_column_available':bool(dsymbol),
          'gamma_symbol_column_available':bool(gsymbol),
          'symbol_comparison_supported':bool(dsymbol and gsymbol),
          'provenance_table_present':bool(table_columns(gg,'decision_provenance') or table_columns(dd,'decision_provenance'))}
        select_cols = ['decision_id',GAMMA_KEY,dtime]+([dsymbol] if dsymbol else [])
        # No raw values are emitted; deterministic bounded walk on rowid.
        def qi(name): return '"' + name.replace('"','""') + '"'
        sql = ('SELECT '+','.join(map(qi,select_cols))+' FROM "decisions" '
               'ORDER BY rowid LIMIT ?')
        gamma_cols=[GAMMA_KEY,'received_at','persisted_at']+([gsymbol] if gsymbol else [])
        lookup=('SELECT '+','.join(map(qi,gamma_cols))+' FROM "gamma_observational_snapshots" '
                'WHERE "canonical_gamma_snapshot_id"=? LIMIT 2')
        c=Counter(); partition=Counter(); gamma_cache={}; seen=set()
        boundary=timestamp(args.reference)
        if boundary is None: raise AuditIssue('INVALID_REFERENCE_TIME')
        try:
            cursor=dd.execute(sql,(args.max_rows+1,))
            for rec in cursor:
                if time.monotonic() >= limit_deadline: raise AuditIssue('TOTAL_TIME_BUDGET_EXHAUSTED')
                c['scanned']+=1
                if c['scanned'] > args.max_rows:
                    r['status']='DECISION_SCAN_TRUNCATED';break
                decision_id,key,when=rec[:3]
                if not isinstance(decision_id,str) or not decision_id.strip() or decision_id in seen:
                    c['invalid_or_duplicate_decision_id']+=1; continue
                seen.add(decision_id)
                dt=timestamp(when)
                if dt is None:
                    c['decision_time_invalid']+=1; continue
                part = 'POST_REFERENCE' if dt>=boundary else 'PRE_REFERENCE'
                partition[part]+=1
                if not isinstance(key,str) or not key.strip():
                    c['missing_canonical_gamma_id']+=1;continue
                if key not in gamma_cache:
                    matches=gg.execute(lookup,(key,)).fetchall()
                    if len(gamma_cache) >= args.max_rows: raise AuditIssue('CACHE_BUDGET_EXHAUSTED')
                    gamma_cache[key]=matches
                matches=gamma_cache[key]
                if not matches: c['gamma_snapshot_not_found']+=1;continue
                if len(matches)>1: c['duplicate_gamma_snapshot_id']+=1;continue
                g=matches[0]; c['exact_id_correlated']+=1
                if dsymbol and gsymbol:
                    actual_sym=rec[3]; gamma_sym=g[3]
                    if not actual_sym or not gamma_sym:
                        c['symbol_unverifiable']+=1;continue
                    if str(actual_sym).upper()!=str(gamma_sym).upper():
                        c['symbol_mismatch']+=1;continue
                    c['symbol_correlated']+=1
                else: c['symbol_comparison_unavailable']+=1
                received=timestamp(g[1]); persisted=timestamp(g[2])
                if received is None or persisted is None:
                    c['receipt_or_persistence_timestamp_invalid_or_missing']+=1;continue
                if persisted < received:
                    c['persistence_before_receipt_claim_conflict']+=1;continue
                if received > dt:
                    c['receipt_after_decision']+=1;continue
                if persisted > dt:
                    c['persistence_after_decision']+=1;continue
                c['receipt_and_persistence_predecision_claim_matches']+=1
        except sqlite3.OperationalError as e:
            # Includes progress-handler interruption and locked files.
            r['status']='SQLITE_QUERY_FAILED_CLOSED';r['error_class']='SQLITE_OPERATIONAL_ERROR';return r
        # No potentially identifying sample identifiers or individual event times.
        r['counts']={k:int(v) for k,v in sorted(c.items())}
        r['partition_counts']={k:int(v) for k,v in sorted(partition.items())}
        r['gates']['bounded_coverage']='PARTIAL' if r['status']=='DECISION_SCAN_TRUNCATED' else 'BOUNDED_WALK_COMPLETED_TOTAL_UNKNOWN'
        r['gates']['exact_gamma_id_correlation']='STORED_RECORD_CORRELATION_NOT_ATTESTATION' if c['exact_id_correlated'] else 'NO_MATCHES'
        r['gates']['stored_receipt_and_persistence_predecision']='STORED_TIMESTAMP_CLAIMS_ONLY' if c['receipt_and_persistence_predecision_claim_matches'] else 'UNVERIFIED'
        if r['status']!='DECISION_SCAN_TRUNCATED':
            r['status']='BOUNDED_RECEIPT_CORRELATION_COMPLETED_NOT_ATTESTED'
        return r


def save(dest, report, root):
    d=Path(dest)
    if d.is_symlink(): raise AuditIssue('OUTPUT_SYMLINK_REJECTED')
    p=d.resolve()
    protected=Path(root).resolve()
    if protected==p or protected in p.parents or (p!=Path('/tmp') and Path('/tmp') not in p.parents):
        raise AuditIssue('OUTPUT_MUST_BE_UNDER_TMP_OUTSIDE_ROOT')
    if p.exists() and not p.is_file(): raise AuditIssue('OUTPUT_NOT_A_FILE')
    p.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.apex315-',dir=p.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(report,f,indent=2,sort_keys=True);f.write('\n')
        os.chmod(temp,0o600);os.replace(temp,p)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',default='/data')
    p.add_argument('--stage3b314-report')
    p.add_argument('--require-previous',action='store_true')
    p.add_argument('--decision-db')
    p.add_argument('--gamma-db')
    p.add_argument('--reference',default=REFERENCE)
    p.add_argument('--max-files',type=int,default=250)
    p.add_argument('--max-depth',type=int,default=3)
    p.add_argument('--max-rows',type=int,default=10000)
    p.add_argument('--budget-seconds',type=int,default=30)
    p.add_argument('--output',required=True)
    a=p.parse_args(argv)
    if not(1<=a.max_files<=1000 and 0<=a.max_depth<=5 and 1<=a.max_rows<=50000 and 1<=a.budget_seconds<=120):
        p.error('INVALID_BUDGET')
    try:
        # Validate destination before any database access.
        dest=Path(a.output).resolve();root=Path(a.root).resolve()
        if root==dest or root in dest.parents or Path('/tmp') not in dest.parents:
            raise AuditIssue('OUTPUT_MUST_BE_UNDER_TMP_OUTSIDE_ROOT')
        report=audit(a)
        save(a.output,report,a.root)
    except (AuditIssue, OSError, sqlite3.Error) as e:
        report=base_report();report['status']='INVALID_EVIDENCE_FAIL_CLOSED'
        report['error_class']=type(e).__name__
        # No raw exception text: it may contain a source pathname.
        try: save(a.output,report,a.root)
        except (AuditIssue, OSError): raise SystemExit('Stage3B315: invalid destination or source; no report written')
    print('Stage 3B.3.15:',report['status'],'|',report['migration_authority'])
    return 0 if report['status']=='BOUNDED_RECEIPT_CORRELATION_COMPLETED_NOT_ATTESTED' else 2

if __name__=='__main__':raise SystemExit(main())

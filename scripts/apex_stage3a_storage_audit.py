#!/usr/bin/env python3
"""APEX Stage 3A: external, read-only SQLite growth/capacity/retention audit.

No SQLite initialization, backup, checkpoint, pragma mutation, VACUUM, cleanup,
DELETE, Python payload deserialization, or process-side cache flushing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import stat
import time
from pathlib import Path
from typing import Any

SCHEMA = 'apex.stage3a_storage_audit.v1'
WARN_FREE_PCT = 25.0
CRITICAL_FREE_PCT = 15.0
MAX_FILES = 256
MAX_DATABASES = 64
MAX_OBJECTS = 24
MAX_REPORTED_CHANGES = 50
QUARANTINE_PATTERN = re.compile(r'\.corrupt-\d{8,14}(?:\.bak)?$')


def _safe_stat(path: Path):
    """Do not follow links: avoid inspecting arbitrary data outside target root."""
    info = path.lstat()
    return info if stat.S_ISREG(info.st_mode) else None


def _sqlite_metadata(path: Path, *, dbstat: bool = False, query_budget_ms: int = 350) -> dict[str, Any]:
    result: dict[str, Any] = {'status': 'UNAVAILABLE', 'read_only': True}
    conn = None
    try:
        # mode=ro deliberately not immutable: correct WAL-aware inspection.
        conn = sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True, timeout=0.25)
        conn.execute('PRAGMA query_only=ON')
        end = time.monotonic() + max(25, min(query_budget_ms, 2000)) / 1000
        conn.set_progress_handler(lambda: 1 if time.monotonic() >= end else 0, 250)
        page_count = int(conn.execute('PRAGMA page_count').fetchone()[0])
        page_size = int(conn.execute('PRAGMA page_size').fetchone()[0])
        freelist = int(conn.execute('PRAGMA freelist_count').fetchone()[0])
        journal_mode = str(conn.execute('PRAGMA journal_mode').fetchone()[0]).upper()
        tables, indexes = conn.execute("SELECT SUM(type='table'), SUM(type='index') FROM sqlite_schema WHERE type IN ('table','index')").fetchone()
        result = {'status':'OK', 'read_only': True, 'page_count': page_count,
                  'page_size_bytes':page_size, 'freelist_pages':freelist,
                  'reusable_sqlite_bytes':freelist * page_size,
                  'file_reclaim_promised_bytes':0, 'journal_mode':journal_mode,
                  'table_count':int(tables or 0), 'index_count':int(indexes or 0),
                  'allocated_page_bytes':page_count * page_size}
        if dbstat:
            try:
                # Opt-in, time-limited scan. Output is aggregate only.
                rows = conn.execute('SELECT name, SUM(pgsize) AS bytes FROM dbstat GROUP BY name ORDER BY bytes DESC LIMIT ?', (MAX_OBJECTS,)).fetchall()
                result['top_objects'] = [{'name':str(name), 'bytes':int(size)} for name,size in rows]
                result['object_size_status'] = 'OK'
            except (sqlite3.DatabaseError, sqlite3.OperationalError) as exc:
                result['object_size_status'] = 'UNAVAILABLE_OR_BUDGET_EXCEEDED'
                result['object_size_error_type'] = type(exc).__name__
        else:
            result['object_size_status'] = 'SKIPPED_OPT_IN_REQUIRED'
    except (OSError, sqlite3.Error) as exc:
        result['status'] = 'UNAVAILABLE_OR_BUDGET_EXCEEDED'
        result['error_type'] = type(exc).__name__
    finally:
        if conn is not None:
            conn.close()
    return result


def _policy(free_pct: float, warn: float, critical: float, total: int, free: int) -> dict[str, Any]:
    valid = 0 <= critical < warn <= 100
    if not valid:
        warn, critical = WARN_FREE_PCT, CRITICAL_FREE_PCT
    state = 'CRITICAL' if free_pct <= critical else 'WARNING' if free_pct <= warn else 'PASS'
    return {'state':state, 'warn_free_pct':warn, 'critical_free_pct':critical,
            'configuration_valid':valid, 'operator_action_required':state != 'PASS',
            'bytes_to_warning_recovery':max(0, int(total*warn/100)-free),
            'bytes_to_critical_boundary':max(0, int(total*critical/100)-free),
            'automatic_cleanup':False}


def audit(root: str | Path, *, dbstat: bool = False, budget_ms: int = 350,
          warn_pct: float = WARN_FREE_PCT, critical_pct: float = CRITICAL_FREE_PCT) -> dict[str, Any]:
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError('Root must be an existing, non-symlink directory')
    root = root.resolve()
    fs = os.statvfs(root)
    total = fs.f_blocks * fs.f_frsize
    free = fs.f_bavail * fs.f_frsize  # operator-available blocks, not privileged f_bfree
    pct = (100.0 * free / total) if total else 0.0
    inventory: list[dict[str, Any]] = []
    dbs: list[dict[str, Any]] = []
    wal_sum = 0
    protected_sum = 0
    quarantined_sum = 0
    omitted = 0
    scanned = 0
    # scandir of immediate children only; no traversal and no opens for non-SQLite files.
    for p in sorted(root.iterdir(), key=lambda x: x.name):
        name = p.name
        if '.db' not in name:
            continue
        if scanned >= MAX_FILES:
            omitted += 1
            continue
        scanned += 1
        try:
            info = _safe_stat(p)
        except OSError:
            continue
        if info is None:
            inventory.append({'name':name,'class':'NON_REGULAR_OR_SYMLINK_SKIPPED'})
            continue
        size = info.st_size
        if name.endswith('.db-wal'):
            cls='SQLITE_WAL_ACTIVE_PROTECTED'; wal_sum += size
        elif name.endswith('.db-shm'):
            cls='SQLITE_SHM_ACTIVE_PROTECTED'
        elif QUARANTINE_PATTERN.search(name):
            cls='QUARANTINED_REVIEW_ONLY'; quarantined_sum += size
        elif name.endswith('.db'):
            cls='ACTIVE_DATABASE_PROTECTED'; protected_sum += size
        else:
            cls='UNKNOWN_DB_ARTIFACT_PROTECTED'
        inventory.append({'name':name,'bytes':size,'class':cls,
                          'mtime_utc':dt.datetime.fromtimestamp(info.st_mtime,dt.timezone.utc).isoformat(),
                          'cleanup_authorized':False})
        if cls == 'ACTIVE_DATABASE_PROTECTED' and len(dbs) < MAX_DATABASES:
            dbs.append({'name':name, 'file_bytes':size,
                        'wal_bytes':0, 'shm_bytes':0,
                        'metadata':_sqlite_metadata(p,dbstat=dbstat,query_budget_ms=budget_ms)})
    size_by_name = {e['name']:e['bytes'] for e in inventory if 'bytes' in e}
    for d in dbs:
        d['wal_bytes'] = size_by_name.get(d['name']+'-wal',0)
        d['shm_bytes'] = size_by_name.get(d['name']+'-shm',0)
        d['total_on_disk_bytes'] = d['file_bytes']+d['wal_bytes']+d['shm_bytes']
    dbs.sort(key=lambda d:d['total_on_disk_bytes'],reverse=True)
    state = _policy(pct,warn_pct,critical_pct,total,free)
    return {'schema':SCHEMA, 'observed_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
            'root':str(root), 'mode':'READ_ONLY', 'dbstat_opt_in':dbstat,
            'capacity':{'total_bytes':total, 'available_bytes':free, 'available_pct':round(pct,3),
                        **state},
            'inventory':inventory, 'databases':dbs,
            'inventory_limits':{'max_files':MAX_FILES,'max_databases':MAX_DATABASES,
                                'omitted_files':omitted,'database_count_capped':len(dbs)==MAX_DATABASES},
            'accounting':{'database_file_bytes':protected_sum,'wal_bytes':wal_sum,
                          'quarantined_review_bytes':quarantined_sum,
                          'quarantine_bytes_automatically_reclaimable':0,
                          'sqlite_freelist_is_filesystem_free':False},
            'retention_guardrails':{
                'canonical_evidence_preserved':True,
                'active_sqlite_files_protected':True,
                'quarantine_requires_age_provenance_backup_and_human_review':True,
                'retention_eligibility_not_inferred_from_file_age':True,
                'no_delete':True,'no_checkpoint':True,'no_vacuum':True,
                'no_schema_mutation':True,'backup_verified':False,
                'no_automatic_archiving':True,'no_execution_or_trade_authority':True,
                'recommended_order':[
                    'EXPAND_PERSISTENT_DISK_IF_WARNING',
                    'VERIFY_EXTERNAL_BACKUP_AND_RESTORE_CAPABILITY',
                    'REVIEW_LARGEST_DATABASES_WITH_OPTIONAL_BOUNDED_DBSTAT',
                    'REVIEW_EXISTING_RETENTION_POLICY_WITH_CANONICAL_EVIDENCE_OWNERS',
                    'APPROVE_FUTURE_CHANGES_SEPARATELY']},
            'confidence':{'table_and_index_sizes':'NOT_MEASURED' if not dbstat else 'DBSTAT_TIME_LIMITED',
                          'size_growth_requires_repeat_snapshots':True,
                          'zero_filesystem_reclaim_guarantee':True}}


def compare(previous: dict[str,Any], current: dict[str,Any]) -> dict[str,Any]:
    if previous.get('schema') != SCHEMA or current.get('schema') != SCHEMA:
        raise ValueError('Incompatible Stage 3A snapshot schema')
    if previous.get('root') != current.get('root'):
        raise ValueError('Cannot compare snapshots from different storage roots')
    start = dt.datetime.fromisoformat(previous['observed_at_utc'])
    end = dt.datetime.fromisoformat(current['observed_at_utc'])
    seconds = (end-start).total_seconds()
    if seconds <= 0:
        raise ValueError('Snapshot observations must be chronologically ordered')
    prev = {r['name']:r['bytes'] for r in previous['inventory'] if 'bytes' in r}
    curr = {r['name']:r['bytes'] for r in current['inventory'] if 'bytes' in r}
    changes = [{'name':name,'previous_bytes':prev.get(name,0),'current_bytes':curr.get(name,0),
                'delta_bytes':curr.get(name,0)-prev.get(name,0)} for name in prev.keys() | curr.keys()]
    changes.sort(key=lambda r:abs(r['delta_bytes']),reverse=True)
    return {'seconds_between_samples':seconds,'changed_files':changes[:MAX_REPORTED_CHANGES],
            'truncated':len(changes)>MAX_REPORTED_CHANGES,
            'free_space_delta_bytes':current['capacity']['available_bytes']-previous['capacity']['available_bytes'],
            'growth_rate_projection_not_established':True,
            'notes':'File deltas include WAL/checkpoint effects, not necessarily new logical evidence.'}


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description='APEX Stage 3A read-only SQLite capacity and retention audit')
    p.add_argument('--root',default='/data',help='Existing persistent storage directory')
    p.add_argument('--output',help='Optional JSON snapshot path outside the database root')
    p.add_argument('--compare',help='Previous Stage 3A JSON snapshot (same storage root)')
    p.add_argument('--dbstat',action='store_true',help='Opt-in, time-budgeted per-object page allocation scan')
    p.add_argument('--query-budget-ms',type=int,default=350)
    p.add_argument('--warn-free-pct',type=float,default=WARN_FREE_PCT)
    p.add_argument('--critical-free-pct',type=float,default=CRITICAL_FREE_PCT)
    args=p.parse_args(argv)
    report=audit(args.root,dbstat=args.dbstat,budget_ms=args.query_budget_ms,
                 warn_pct=args.warn_free_pct,critical_pct=args.critical_free_pct)
    if args.compare:
        prior=json.loads(Path(args.compare).read_text(encoding='utf-8'))
        report['comparison']=compare(prior, report)
    rendered=json.dumps(report,indent=2,sort_keys=True)
    if args.output:
        output=Path(args.output).resolve()
        if output == Path(args.root).resolve() or Path(args.root).resolve() in output.parents:
            p.error('Refusing to write audit output inside the live database root')
        output.write_text(rendered+'\n',encoding='utf-8')
    else:
        print(rendered)
    return 0

if __name__=='__main__':
    raise SystemExit(main())

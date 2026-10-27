"""Durable scanner-owned lifecycle journal; diagnostic only, never a scheduler input."""
from __future__ import annotations
import datetime as dt
import os
import sqlite3
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

SCHEMA = 'apex.scanner_coverage.v2'
BOOT_ID = uuid.uuid4().hex
_ET = ZoneInfo('America/New_York')


def _path():
    return Path(os.getenv('APEX_SCANNER_COVERAGE_DB', '/data/apex_scanner_coverage.db'))


def record(event, *, duration=None, reason=None, occurred_at=None, attempt_id=None):
    """Fail-open; scanner never waits on observability storage failures."""
    if os.getenv('APEX_SCANNER_PROCESS', '').lower() != 'true':
        return False
    try:
        timestamp = occurred_at or dt.datetime.now(dt.timezone.utc)
        if isinstance(timestamp, str):
            timestamp = dt.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
        timestamp = timestamp.astimezone(dt.timezone.utc)
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(path), timeout=0.25) as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS scanner_events (id TEXT PRIMARY KEY, boot_id TEXT NOT NULL, pid INTEGER NOT NULL, session_date TEXT NOT NULL, occurred_at TEXT NOT NULL, event TEXT NOT NULL, duration REAL, reason TEXT)')
            # In-place additive migration; old rows remain immutable and unpaired.
            columns = {row[1] for row in conn.execute('PRAGMA table_info(scanner_events)')}
            if 'attempt_id' not in columns:
                conn.execute('ALTER TABLE scanner_events ADD COLUMN attempt_id TEXT')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_scanner_events_session ON scanner_events(session_date, occurred_at)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_scanner_events_attempt ON scanner_events(attempt_id)')
            if attempt_id is not None:
                attempt_id = str(attempt_id)
                if not attempt_id or len(attempt_id) > 128:
                    return False
                if event == 'ATTEMPT':
                    if conn.execute('SELECT 1 FROM scanner_events WHERE attempt_id=? LIMIT 1', (attempt_id,)).fetchone():
                        return False
                elif event in ('COMPLETED', 'FAILED', 'LOCK_BUSY'):
                    origin = conn.execute("SELECT boot_id,pid FROM scanner_events WHERE attempt_id=? AND event='ATTEMPT' LIMIT 1", (attempt_id,)).fetchone()
                    if origin != (BOOT_ID, os.getpid()):
                        return False
                    if conn.execute("SELECT 1 FROM scanner_events WHERE attempt_id=? AND event IN ('COMPLETED','FAILED','LOCK_BUSY') LIMIT 1", (attempt_id,)).fetchone():
                        return False
            conn.execute('INSERT INTO scanner_events (id,boot_id,pid,session_date,occurred_at,event,duration,reason,attempt_id) VALUES (?,?,?,?,?,?,?,?,?)', (
                uuid.uuid4().hex, BOOT_ID, os.getpid(), timestamp.astimezone(_ET).date().isoformat(),
                timestamp.isoformat(), str(event), duration, str(reason)[:200] if reason else None, attempt_id))
        return True
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return False


def read_coverage(session_date=None):
    """Cross-process historical facts, including after the scanner stops."""
    try:
        session_date = session_date or dt.datetime.now(_ET).date().isoformat()
        path = _path()
        if not path.is_file():
            return {'available': False, 'reason': 'NO_PERSISTED_COVERAGE', 'session_date': session_date}
        # Read-only SQLite connection: web must not initialize or mutate journal.
        with sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=0.25) as conn:
            rows = conn.execute('SELECT event, COUNT(*), MAX(occurred_at) FROM scanner_events WHERE session_date=? GROUP BY event', (session_date,)).fetchall()
            last = conn.execute('SELECT occurred_at, event, duration, boot_id, pid FROM scanner_events WHERE session_date=? ORDER BY occurred_at DESC, rowid DESC LIMIT 1', (session_date,)).fetchone()
            completed_last = conn.execute("SELECT occurred_at, event, duration, boot_id, pid FROM scanner_events WHERE session_date=? AND event='COMPLETED' ORDER BY occurred_at DESC, rowid DESC LIMIT 1", (session_date,)).fetchone()
            boots = conn.execute('SELECT COUNT(DISTINCT boot_id) FROM scanner_events WHERE session_date=?', (session_date,)).fetchone()[0]
            columns = {r[1] for r in conn.execute('PRAGMA table_info(scanner_events)')}
            lineage = None
            if 'attempt_id' in columns:
                lineage = conn.execute('''SELECT a.attempt_id, a.boot_id, a.pid, a.occurred_at,
                    (SELECT t.event FROM scanner_events t WHERE t.attempt_id=a.attempt_id
                     AND t.event IN ('COMPLETED','FAILED','LOCK_BUSY') ORDER BY t.occurred_at LIMIT 1)
                    FROM scanner_events a WHERE a.session_date=? AND a.event='ATTEMPT'
                    AND a.attempt_id IS NOT NULL ORDER BY a.occurred_at DESC''', (session_date,)).fetchall()
                legacy = conn.execute("SELECT COUNT(*) FROM scanner_events WHERE session_date=? AND event='ATTEMPT' AND attempt_id IS NULL", (session_date,)).fetchone()[0]
        counts = {event: count for event, count, _ in rows}
        from engine.scanner_session_gate_audit import classify_unresolved
        now = dt.datetime.now(dt.timezone.utc)
        last_age = None
        if last:
            last_time = dt.datetime.fromisoformat(last[0].replace('Z', '+00:00'))
            last_age = max(0.0, (now - last_time).total_seconds())
        unresolved = classify_unresolved(counts.get('ATTEMPT', 0),
            counts.get('COMPLETED', 0), counts.get('FAILED', 0),
            counts.get('LOCK_BUSY', 0), last[1] if last else None, last_age)
        if lineage is not None:
            open_rows = [r for r in lineage if r[4] is None]
            cutoff = now - dt.timedelta(seconds=600)
            recent = [r for r in open_rows if dt.datetime.fromisoformat(r[3]) >= cutoff]
            stale = [r for r in open_rows if dt.datetime.fromisoformat(r[3]) < cutoff]
            reconciliation = {'state': 'READY', 'correlated_attempts': len(lineage),
                'paired_terminal_events': len(lineage)-len(open_rows),
                'recent_open': len(recent), 'stale_open': len(stale),
                'legacy_uncorrelated_attempts': legacy,
                'stale_examples': [{'attempt_id': r[0], 'boot_id': r[1], 'pid': r[2], 'at': r[3]} for r in stale[:10]],
                'stale_classification': 'UNCONFIRMED_NOT_A_FAILURE',
                'read_only': True, 'execution_authority': False}
        else:
            reconciliation = {'state': 'LEGACY_SCHEMA', 'read_only': True}
        return {'available': True, 'attempt_reconciliation': reconciliation, 'unresolved_attempts': unresolved, 'schema': SCHEMA, 'session_date': session_date,
                'attempts': counts.get('ATTEMPT', 0), 'completed': counts.get('COMPLETED', 0),
                'failures': counts.get('FAILED', 0), 'lock_skips': counts.get('LOCK_BUSY', 0),
                'boot_instances': boots, 'last_event': ({'at': last[0], 'event': last[1],
                'duration_seconds': last[2], 'boot_id': last[3], 'pid': last[4]} if last else None),
                'last_completed_event': ({'at': completed_last[0], 'event': completed_last[1], 'duration_seconds': completed_last[2], 'boot_id': completed_last[3], 'pid': completed_last[4]} if completed_last else None),
                'authority': 'PERSISTED_SCANNER_EVENTS', 'execution_authority': False,
                'decision_authority': False}
    except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
        return {'available': False, 'reason': type(exc).__name__, 'session_date': session_date}

"""APEX 50.6.5.3 — persisted asynchronous Anthropic narrative jobs."""
from __future__ import annotations
import datetime as dt, json, os, sqlite3, threading, time
from typing import Optional

VERSION = "50.6.5.4_NONBLOCKING_MORNING_BRIEF"
STALE_SECONDS = max(60.0, min(float(os.getenv("APEX_ASYNC_NARRATIVE_STALE_SECONDS", "180")), 1800.0))
_LOCK = threading.RLock()
_ACTIVE: set[str] = set()
_ENQUEUE_ACTIVE: set[str] = set()


def _db_path() -> str:
    p = os.getenv("APEX_ASYNC_NARRATIVE_DB", "").strip()
    if p: return p
    if os.path.isdir('/data') and os.access('/data', os.W_OK): return '/data/apex_async_narrative.db'
    return 'apex_async_narrative.db'


def _conn():
    c=sqlite3.connect(_db_path(), timeout=5)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""CREATE TABLE IF NOT EXISTS narrative_jobs(
      job_key TEXT PRIMARY KEY, status TEXT NOT NULL, narrative TEXT, error TEXT,
      telemetry_json TEXT, created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT,
      updated_at TEXT NOT NULL, attempt_count INTEGER NOT NULL DEFAULT 0,
      target_session_date TEXT, brief_mode TEXT, model TEXT, version TEXT NOT NULL)""")
    return c


def _now(): return dt.datetime.now(dt.timezone.utc).isoformat()

def job_key(target_session_date:str, brief_mode:str) -> str:
    return f"SPX:{target_session_date}:{str(brief_mode).upper()}"

def get_job(key:str) -> Optional[dict]:
    try:
        with _conn() as c:
            r=c.execute("SELECT * FROM narrative_jobs WHERE job_key=?",(key,)).fetchone()
        if not r: return None
        d=dict(r); d['telemetry']=json.loads(d.pop('telemetry_json') or '{}'); d['version']=VERSION
        return d
    except Exception as exc:
        return {'job_key':key,'status':'UNAVAILABLE','error':f'{type(exc).__name__}: {exc}','telemetry':{},'version':VERSION}

def _upsert(key,status,**fields):
    now=_now(); fields.setdefault('updated_at',now)
    with _conn() as c:
        exists=c.execute("SELECT 1 FROM narrative_jobs WHERE job_key=?",(key,)).fetchone()
        if not exists:
            c.execute("INSERT INTO narrative_jobs(job_key,status,created_at,updated_at,version,target_session_date,brief_mode,model) VALUES(?,?,?,?,?,?,?,?)",
                      (key,status,now,now,VERSION,fields.pop('target_session_date',None),fields.pop('brief_mode',None),fields.pop('model',None)))
        sets=['status=?']; vals=[status]
        for k,v in fields.items():
            if k=='telemetry': k='telemetry_json'; v=json.dumps(v,default=str)
            sets.append(f'{k}=?'); vals.append(v)
        vals.append(key); c.execute(f"UPDATE narrative_jobs SET {', '.join(sets)} WHERE job_key=?",vals)

def schedule(*, key:str, prompt:str, api_key:str, model:str, target_session_date:str, brief_mode:str, force:bool=False) -> dict:
    existing=get_job(key)
    if existing and existing.get('status') in {'PENDING','RUNNING'} and not force:
        try:
            updated=dt.datetime.fromisoformat(str(existing.get('updated_at') or '').replace('Z','+00:00'))
            age=(dt.datetime.now(dt.timezone.utc)-updated.astimezone(dt.timezone.utc)).total_seconds()
        except Exception:
            age=0.0
        if age < STALE_SECONDS:
            return existing
        force=True  # stale job from a dead/restarted worker; safely requeue
    if existing and existing.get('status')=='COMPLETE' and not force: return existing
    _upsert(key,'PENDING',target_session_date=target_session_date,brief_mode=brief_mode,model=model,error=None,narrative=None,telemetry={},attempt_count=0,started_at=None,completed_at=None)
    def worker():
        with _LOCK:
            if key in _ACTIVE: return
            _ACTIVE.add(key)
        try:
            _upsert(key,'RUNNING',started_at=_now())
            from .morning_brief import call_anthropic
            narrative,error,telemetry=call_anthropic(prompt,api_key=api_key,model=model)
            attempts=len((telemetry or {}).get('attempts') or [])
            if narrative:
                _upsert(key,'COMPLETE',narrative=narrative,error=None,telemetry=telemetry,attempt_count=attempts,completed_at=_now())
            else:
                _upsert(key,'FAILED',narrative=None,error=error or 'Narrative generation failed',telemetry=telemetry,attempt_count=attempts,completed_at=_now())
        except Exception as exc:
            _upsert(key,'FAILED',error=f'{type(exc).__name__}: {exc}',telemetry={'outcome':'WORKER_EXCEPTION'},completed_at=_now())
        finally:
            with _LOCK: _ACTIVE.discard(key)
    threading.Thread(target=worker,name=f'apex-narrative-{abs(hash(key))%10000}',daemon=True).start()
    return get_job(key) or {'job_key':key,'status':'PENDING','version':VERSION}


def enqueue_nonblocking(*, key:str, prompt:str, api_key:str, model:str, target_session_date:str, brief_mode:str, force:bool=False) -> dict:
    """Launch persistence + worker scheduling without blocking the HTTP request.

    This function intentionally performs no SQLite access on the caller thread.
    The dashboard may observe NOT_FOUND for the first polling cycle; the launcher
    creates PENDING/RUNNING state asynchronously.
    """
    with _LOCK:
        if key in _ENQUEUE_ACTIVE or key in _ACTIVE:
            return {"job_key": key, "status": "ALREADY_QUEUED", "version": VERSION, "nonblocking": True}
        _ENQUEUE_ACTIVE.add(key)

    def launcher():
        try:
            schedule(
                key=key, prompt=prompt, api_key=api_key, model=model,
                target_session_date=target_session_date, brief_mode=brief_mode,
                force=force,
            )
        except Exception:
            # schedule() persists detailed worker errors when it reaches the store.
            # If even the store is unavailable, narrative-status reports UNAVAILABLE.
            pass
        finally:
            with _LOCK:
                _ENQUEUE_ACTIVE.discard(key)

    threading.Thread(
        target=launcher,
        name=f'apex-narrative-enqueue-{abs(hash(key))%10000}',
        daemon=True,
    ).start()
    return {"job_key": key, "status": "ENQUEUED", "version": VERSION, "nonblocking": True}

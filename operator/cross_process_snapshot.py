"""One-shot, read-only container process / file-cache accounting snapshot.

Usage (inside the Render instance): python cross_process_snapshot.py > memory_snapshot.json
No database queries, gc, process signalling, or kernel state changes.
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone


def _keys(path, wanted):
    try:
        return {k: v.strip() for line in path.read_text().splitlines()
                for k, sep, v in [line.partition(':')]
                if sep and k in wanted}
    except (OSError, ValueError, PermissionError):
        return {}


def _start_ticks(pid):
    try:
        data = Path(f'/proc/{pid}/stat').read_text()
        # Comm is enclosed in parentheses and may itself contain spaces.
        trailing = data[data.rfind(')')+2:].split()
        return int(trailing[19])  # field 22, counted from field 3 at offset 19
    except (OSError, ValueError, IndexError):
        return None


def process_snapshot(pid):
    start_before = _start_ticks(pid)
    if start_before is None:
        return None
    stat = _keys(Path(f'/proc/{pid}/status'), {'Name', 'VmRSS', 'RssAnon', 'RssFile', 'RssShmem'})
    smaps = _keys(Path(f'/proc/{pid}/smaps_rollup'), {'Rss','Pss','Private_Dirty'})
    start_after = _start_ticks(pid)
    if start_after != start_before or not stat:
        return None
    return {'pid':pid,'process_start_ticks':start_before,'name':stat.get('Name'),
            'status_kib':stat, 'smaps_kib':smaps}


def cgroup_snapshot(root=Path('/sys/fs/cgroup')):
    keys = {'anon','file','active_file','inactive_file','kernel','slab','shmem'}
    try:
        stats = {k:int(v) for line in (root/'memory.stat').read_text().splitlines()
                 for k,v in [line.split(None,1)] if k in keys}
    except (OSError,ValueError):
        stats = {}
    try:
        events = {k:int(v) for line in (root/'memory.events').read_text().splitlines()
                  for k,v in [line.split(None,1)] if k in {'max','oom','oom_kill'}}
    except (OSError,ValueError):
        events = {}
    def read_number(name):
        try: return int((root/name).read_text().strip())
        except (OSError,ValueError): return None
    return {'current_bytes':read_number('memory.current'), 'limit_bytes':read_number('memory.max'),
            'memory_stat_bytes':stats,'memory_events':events}


def collect(max_processes=64):
    # Limit /proc work. Explicitly identify partial visibility rather than assuming
    # that a sum of sampled processes must match cgroup anonymous memory.
    all_pids = sorted(int(p.name) for p in Path('/proc').iterdir() if p.name.isdecimal())
    limit = max(1,min(int(max_processes),64))
    processes = [row for pid in all_pids[:limit] if (row:=process_snapshot(pid)) is not None]
    return {'schema':'apex.cross_process_memory_snapshot.v1',
            'observed_at':datetime.now(timezone.utc).isoformat(),
            'cgroup':cgroup_snapshot(), 'processes':processes,
            'process_visibility_truncated':len(all_pids)>limit,
            'processes_listed':len(all_pids),
            'notes':['Per-process RSS overlaps shared mappings and cannot be summed as a cgroup total',
                     'Separate snapshots must match pid and process_start_ticks to support continuity',
                     'No SQLite database files are read or modified'],
            'read_only':True,'execution_authority':False,'decision_authority':False}


if __name__ == '__main__':
    print(json.dumps(collect(),indent=2))

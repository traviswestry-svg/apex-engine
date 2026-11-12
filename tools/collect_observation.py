#!/usr/bin/env python3
"""One-shot, read-only comparison of APEX /health memory counters. No server changes."""
import argparse
import datetime as dt
import json
import pathlib
import ssl
import sys
import urllib.request

BASELINE = pathlib.Path(__file__).resolve().parents[1] / 'baseline_20261112_1031_ET.json'
DEFAULT_URL = 'https://apex-engine-dashboard.onrender.com/health'
EVENTS = ('max','oom','oom_kill','high','low','oom_group_kill')

def load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)

def obtain(url, timeout):
    req = urllib.request.Request(url,headers={'User-Agent':'APEX-Memory-Observation/1.0','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout,context=ssl.create_default_context()) as response:
        # 2 MiB bound: ordinary health response is small; fail closed for unexpectedly large body.
        content = response.read(2*1024*1024+1)
    if len(content)>2*1024*1024:
        raise ValueError('Health payload exceeds 2 MiB maximum')
    return json.loads(content.decode('utf-8'))

def nested(obj,*keys):
    for key in keys:
        if not isinstance(obj,dict): return None
        obj=obj.get(key)
    return obj

def diff_integer(a,b):
    return b-a if type(a) is int and type(b) is int else None

def compare(baseline, current):
    b_lim=baseline.get('container_memory_limit_event_investigation') or {}
    c_lim=current.get('container_memory_limit_event_investigation') or {}
    b_inv=baseline.get('runtime_memory_investigation') or {}
    c_inv=current.get('runtime_memory_investigation') or {}
    b_cgroup=b_inv.get('cgroup') or {}; c_cgroup=c_inv.get('cgroup') or {}
    b_events=b_cgroup.get('events_cumulative') or b_lim.get('cumulative_events_at_last_sample') or {}
    c_events=c_cgroup.get('events_cumulative') or c_lim.get('cumulative_events_at_last_sample') or {}
    bp=nested(b_inv,'web_process','pid'); cp=nested(c_inv,'web_process','pid')
    b_worker=b_lim.get('web_worker_pid'); c_worker=c_lim.get('web_worker_pid')
    same_web_worker=(bp==cp and b_worker==c_worker and bp==b_worker and cp==c_worker)
    cgroup_verified=(b_lim.get('cgroup_identity_verified') is True and c_lim.get('cgroup_identity_verified') is True)
    b_t=b_lim.get('observed_at'); c_t=c_lim.get('observed_at')
    chronological = isinstance(b_t,str) and isinstance(c_t,str) and c_t > b_t
    # A restart or worker switch invalidates the process-local baseline; even same worker pid
    # cannot identify the cgroup across restarts without an independently verified identity.
    same_process_start = baseline.get('process_started_at') == current.get('process_started_at') and bool(current.get('process_started_at'))
    comparable= all((same_web_worker, cgroup_verified, chronological, same_process_start)) and all(
        type(b_events.get(k)) is int and type(c_events.get(k)) is int and c_events[k]>=b_events[k] for k in EVENTS)
    delta={k:diff_integer(b_events.get(k),c_events.get(k)) if comparable else None for k in EVENTS}
    mem_fields={'cgroup_current_bytes': ('current_bytes',),
                'anonymous_bytes':('accounting','anon_bytes'),
                'file_bytes':('accounting','file_bytes'),
                'inactive_file_bytes':('accounting','inactive_file_bytes')}
    mem_delta={name:diff_integer(nested(b_cgroup,*path),nested(c_cgroup,*path)) if comparable else None for name,path in mem_fields.items()}
    return {'assessment':('NEW_LIMIT_EVENTS' if delta['max'] and delta['max']>0 else 'NO_NEW_LIMIT_EVENTS') if comparable else 'INCOMPARABLE_OBSERVATIONS',
            'baseline_at':b_t,'new_observation_at':c_t,
            'same_web_worker':same_web_worker,'same_process_start':same_process_start,
            'cgroup_identity_verified_on_both':cgroup_verified,'chronological':chronological,
            'baseline_worker_pid':b_worker,'current_worker_pid':c_worker,
            'baseline_counters':{k:b_events.get(k) for k in EVENTS},
            'current_counters':{k:c_events.get(k) for k in EVENTS},'new_event_counts':delta,
            'memory_deltas_bytes':mem_delta,
            'current_raw_usage_pct':nested(current,'memory_pressure','raw_usage_pct'),
            'current_noninactive_usage_pct':nested(current,'memory_pressure','estimated_noninactive_file_usage_pct'),
            'current_psi_some_avg10':nested(current,'memory_pressure','psi_some_avg10'),
            'current_psi_full_avg10':nested(current,'memory_pressure','psi_full_avg10'),
            'current_instrument_status':c_lim.get('status'),
            'current_instrument_samples':c_lim.get('sample_count'),
            'current_instrument_new_max_intervals':c_lim.get('new_max_event_intervals'),
            'note':'Temporal intervals do not establish scanner/settlement causation. Different workers or restarts cannot be directly subtracted.'}

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline',default=str(BASELINE))
    src=ap.add_mutually_exclusive_group()
    src.add_argument('--file',help='Saved new /health JSON (offline comparison)')
    src.add_argument('--url',help='Production /health URL (default if --file omitted)')
    ap.add_argument('--timeout',type=float,default=12.0)
    ap.add_argument('--out',default='apex_second_memory_observation.json')
    args=ap.parse_args(argv)
    try:
        newer=load(args.file) if args.file else obtain(args.url or DEFAULT_URL,args.timeout)
        result=compare(load(args.baseline),newer)
        pathlib.Path(args.out).write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        print(json.dumps(result,indent=2))
        print('\nSaved:',args.out)
        return 0 if result['assessment']!='INCOMPARABLE_OBSERVATIONS' else 2
    except Exception as exc:
        print(f'Observation failed: {exc}',file=sys.stderr)
        return 1
if __name__=='__main__': sys.exit(main())

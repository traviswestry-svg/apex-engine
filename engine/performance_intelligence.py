"""APEX 16.5 — Performance Intelligence.

Governed, descriptive performance coaching across completed outcomes. This module
never changes live confidence, recommendations, playbooks, risk limits, or orders.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, sqlite3, uuid
from collections import defaultdict
from typing import Any
from . import institutional_governance as gov

VERSION='16.5.16.5'; SCHEMA_VERSION='apex.performance_intelligence.v1'
DIMENSIONS=('market_state','playbook','entry_window','weekday','volatility_regime','gamma_regime','execution_behavior','alpha_source','drawdown_source')

def _now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def _json(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def _load(v,d=None):
    try:return json.loads(v)
    except Exception:return {} if d is None else d
def _conn():
    c=sqlite3.connect(gov.DB_PATH); c.row_factory=sqlite3.Row; return c

def init_db():
    gov.init_db()
    with _conn() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS performance_intelligence_observations(
          observation_id TEXT PRIMARY KEY, trade_id TEXT NOT NULL UNIQUE, symbol TEXT NOT NULL,
          closed_at TEXT NOT NULL, outcome_json TEXT NOT NULL, dimensions_json TEXT NOT NULL,
          schema_version TEXT NOT NULL, engine_version TEXT NOT NULL, integrity_hash TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_pi_symbol_time ON performance_intelligence_observations(symbol,closed_at);
        CREATE TABLE IF NOT EXISTS performance_intelligence_analyses(
          analysis_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, as_of TEXT NOT NULL, sample_size INTEGER NOT NULL,
          filters_json TEXT NOT NULL, analysis_json TEXT NOT NULL, schema_version TEXT NOT NULL,
          engine_version TEXT NOT NULL, integrity_hash TEXT NOT NULL, created_at TEXT NOT NULL);
        ''')
    return {'ok':True,'schema_version':SCHEMA_VERSION,'build_version':VERSION}

def _num(v,d=0.0):
    try:return float(v)
    except Exception:return d

def _weekday(closed_at):
    try:return dt.datetime.fromisoformat(str(closed_at).replace('Z','+00:00')).strftime('%A').upper()
    except Exception:return 'UNKNOWN'

def _entry_window(opened_at):
    try:
        x=dt.datetime.fromisoformat(str(opened_at).replace('Z','+00:00')); m=x.hour*60+x.minute
        if m<585:return 'OPENING_0930_0945'
        if m<630:return 'MORNING_0945_1030'
        if m<690:return 'LATE_MORNING_1030_1130'
        if m<810:return 'MIDDAY_1130_1330'
        return 'AFTERNOON'
    except Exception:return 'UNKNOWN'

def normalize_trade(t:dict)->dict:
    closed=t.get('closed_at') or _now(); pnl=_num(t.get('net_pnl',t.get('pnl',t.get('realized_pnl',0))))
    r=_num(t.get('realized_r',t.get('r_multiple',0)))
    dims=dict(t.get('dimensions') or {})
    dims.setdefault('market_state',t.get('market_state') or 'UNKNOWN')
    dims.setdefault('playbook',t.get('playbook') or 'UNKNOWN')
    dims.setdefault('entry_window',t.get('entry_window') or _entry_window(t.get('opened_at')))
    dims.setdefault('weekday',t.get('weekday') or _weekday(closed))
    dims.setdefault('volatility_regime',t.get('volatility_regime') or 'UNKNOWN')
    dims.setdefault('gamma_regime',t.get('gamma_regime') or 'UNKNOWN')
    dims.setdefault('execution_behavior',t.get('execution_behavior') or ('CLEAN' if not t.get('execution_mistakes') else 'MISTAKE'))
    dims.setdefault('alpha_source',t.get('alpha_source') or t.get('primary_driver') or 'UNKNOWN')
    dims.setdefault('drawdown_source',t.get('drawdown_source') or ('NONE' if pnl>=0 else t.get('loss_reason') or 'UNCLASSIFIED'))
    return {'trade_id':str(t.get('trade_id') or uuid.uuid4()),'symbol':str(t.get('symbol') or 'SPX'),'opened_at':t.get('opened_at'),'closed_at':closed,
            'net_pnl':round(pnl,2),'realized_r':round(r,4),'won':pnl>0,'loss':pnl<0,'dimensions':{k:str(dims.get(k) or 'UNKNOWN').upper() for k in DIMENSIONS}}

def _stats(rows):
    n=len(rows); pnl=sum(x['net_pnl'] for x in rows); wins=sum(x['won'] for x in rows); losses=[x for x in rows if x['loss']]
    rs=[x['realized_r'] for x in rows]
    return {'sample_size':n,'wins':wins,'losses':len(losses),'win_rate':round(100*wins/n,2) if n else 0.0,
            'net_pnl':round(pnl,2),'average_pnl':round(pnl/n,2) if n else 0.0,'average_r':round(sum(rs)/n,4) if n else 0.0,
            'profit_factor':round(sum(max(x['net_pnl'],0) for x in rows)/abs(sum(min(x['net_pnl'],0) for x in rows)),3) if sum(min(x['net_pnl'],0) for x in rows)<0 else None}

def analyze(trades:list[dict]|None=None,*,symbol='SPX',minimum_sample=3)->dict[str,Any]:
    rows=[normalize_trade(x) for x in (trades or []) if isinstance(x,dict)]
    if symbol: rows=[x for x in rows if x['symbol'].upper()==symbol.upper()]
    breakdown={}
    for dim in DIMENSIONS:
        groups=defaultdict(list)
        for row in rows:groups[row['dimensions'][dim]].append(row)
        ranked=[{'value':k,**_stats(v)} for k,v in groups.items()]
        ranked.sort(key=lambda x:(x['average_r'],x['net_pnl'],x['sample_size']),reverse=True)
        breakdown[dim]=ranked
    qualified=[(dim,item) for dim,items in breakdown.items() for item in items if item['sample_size']>=minimum_sample]
    best=sorted(qualified,key=lambda z:(z[1]['average_r'],z[1]['net_pnl']),reverse=True)[:5]
    worst=sorted(qualified,key=lambda z:(z[1]['average_r'],z[1]['net_pnl']))[:5]
    coaching=[]
    for dim,item in worst[:3]:
        if item['average_r']<0: coaching.append({'type':'REVIEW','dimension':dim,'value':item['value'],'message':f"Review {dim}={item['value']}: average outcome {item['average_r']}R across {item['sample_size']} completed trades."})
    return {'status':'READY' if len(rows)>=minimum_sample else 'COLLECTING','symbol':symbol,'sample_size':len(rows),'overall':_stats(rows),'breakdowns':breakdown,
            'top_alpha_sources':[{'dimension':d,**x} for d,x in best],'largest_drawdown_sources':[{'dimension':d,**x} for d,x in worst],
            'coaching':coaching,'minimum_sample':minimum_sample,'descriptive_only':True,'automatic_policy_update_enabled':False,'live_decision_feedback_enabled':False,'production_effect':'NONE'}

def record_observation(trade:dict,actor='SYSTEM'):
    init_db(); x=normalize_trade(trade)
    with _conn() as c:r=c.execute('SELECT * FROM performance_intelligence_observations WHERE trade_id=?',(x['trade_id'],)).fetchone()
    if r:return {'ok':True,'status':'IMMUTABLE_EXISTS','created':False,**_decode_obs(dict(r)),'production_effect':'NONE'}
    payload={'outcome':{k:x[k] for k in ('trade_id','symbol','opened_at','closed_at','net_pnl','realized_r','won','loss')},'dimensions':x['dimensions']}
    ih=hashlib.sha256(_json(payload).encode()).hexdigest(); oid=str(uuid.uuid4()); created=_now()
    with _conn() as c:c.execute('INSERT INTO performance_intelligence_observations VALUES(?,?,?,?,?,?,?,?,?,?)',(oid,x['trade_id'],x['symbol'],x['closed_at'],_json(payload['outcome']),_json(x['dimensions']),SCHEMA_VERSION,VERSION,ih,created))
    gov.audit('CREATE_PERFORMANCE_OBSERVATION','performance_intelligence',oid,new={'trade_id':x['trade_id'],'integrity_hash':ih},actor=actor,explanation='Immutable completed-outcome performance observation')
    return {'ok':True,'status':'CREATED','created':True,'observation_id':oid,**payload,'integrity_hash':ih,'created_at':created,'production_effect':'NONE'}

def _decode_obs(d):d['outcome']=_load(d.pop('outcome_json'));d['dimensions']=_load(d.pop('dimensions_json'));return d

def observations(symbol='SPX',limit=1000):
    init_db()
    with _conn() as c:rows=c.execute('SELECT * FROM performance_intelligence_observations WHERE symbol=? ORDER BY closed_at DESC LIMIT ?',(symbol,max(1,min(int(limit),5000)))).fetchall()
    return [_decode_obs(dict(r)) for r in rows]

def analyze_stored(symbol='SPX',persist=False,actor='SYSTEM'):
    rs=[]
    for r in observations(symbol):rs.append({**r['outcome'],'dimensions':r['dimensions']})
    out=analyze(rs,symbol=symbol)
    if persist:
        aid=str(uuid.uuid4()); created=_now(); as_of=_now(); ih=hashlib.sha256(_json(out).encode()).hexdigest()
        with _conn() as c:c.execute('INSERT INTO performance_intelligence_analyses VALUES(?,?,?,?,?,?,?,?,?,?,?)',(aid,symbol,as_of,out['sample_size'],_json({'symbol':symbol}),_json(out),SCHEMA_VERSION,VERSION,ih,created))
        gov.audit('CREATE_PERFORMANCE_ANALYSIS','performance_intelligence',aid,new={'sample_size':out['sample_size'],'integrity_hash':ih},actor=actor,explanation='Immutable descriptive performance analysis')
        out.update({'analysis_id':aid,'created':True,'integrity_hash':ih,'created_at':created})
    return out

def dashboard(symbol='SPX'):return {'ok':True,'status':'READY','analysis':analyze_stored(symbol),'recent_observations':observations(symbol,50),'safety':status()}
def status():
    init_db()
    with _conn() as c:o=c.execute('SELECT COUNT(*) n FROM performance_intelligence_observations').fetchone()['n'];a=c.execute('SELECT COUNT(*) n FROM performance_intelligence_analyses').fetchone()['n']
    return {'status':'READY','schema_version':SCHEMA_VERSION,'build_version':VERSION,'observation_count':o,'analysis_count':a,'descriptive_only':True,'offline_outcomes_only':True,'automatic_policy_update_enabled':False,'recommendation_mutation_enabled':False,'confidence_mutation_enabled':False,'broker_order_submission_enabled':False,'production_effect':'NONE'}

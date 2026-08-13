"""APEX 16.2 Adaptive Trade Management.

Deterministic, advisory-only management of an already-open trade. The engine
assesses remaining edge, risk progress, playbook/market-state validity, and
profit milestones, then emits evidence-backed recommendations. It never sends,
changes, or cancels broker orders.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, math, sqlite3, uuid
from typing import Any
from . import institutional_governance as gov

VERSION='16.2.16.2'; SCHEMA_VERSION='apex.adaptive_trade_management.v1'

def _now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def _json(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def _conn():
    c=sqlite3.connect(gov.DB_PATH); c.row_factory=sqlite3.Row; return c
def _num(v,default=0.0):
    try:
        x=float(v); return x if math.isfinite(x) else default
    except Exception:return default
def _clamp(v,lo=0.0,hi=100.0): return max(lo,min(hi,float(v)))
def _direction(v):
    s=str(v or '').upper(); return 1 if s in {'LONG','CALL','CALLS','BUY','BULLISH'} else (-1 if s in {'SHORT','PUT','PUTS','SELL','BEARISH'} else 0)
def _pick(d,*keys,default=None):
    for key in keys:
        cur=d; ok=True
        for part in key.split('.'):
            if isinstance(cur,dict) and part in cur: cur=cur[part]
            else: ok=False; break
        if ok and cur is not None:return cur
    return default

def init_db():
    gov.init_db()
    with _conn() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS adaptive_trade_management_events(
          management_id TEXT PRIMARY KEY, trade_id TEXT NOT NULL, symbol TEXT NOT NULL,
          observed_at TEXT NOT NULL, action TEXT NOT NULL, urgency TEXT NOT NULL,
          remaining_edge_score REAL NOT NULL, payload_json TEXT NOT NULL,
          schema_version TEXT NOT NULL, engine_version TEXT NOT NULL,
          integrity_hash TEXT NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(trade_id,observed_at));
        CREATE INDEX IF NOT EXISTS idx_atm_trade_time ON adaptive_trade_management_events(trade_id,observed_at);
        ''')
    return {'ok':True,'schema_version':SCHEMA_VERSION,'build_version':VERSION}

def status():
    init_db()
    with _conn() as c:n=c.execute('SELECT COUNT(*) n FROM adaptive_trade_management_events').fetchone()['n']
    return {'status':'READY','engine':'ADAPTIVE_TRADE_MANAGEMENT','build_version':VERSION,
      'schema_version':SCHEMA_VERSION,'event_count':n,'deterministic':True,
      'advisory_only':True,'future_information_allowed':False,'broker_order_submission_enabled':False,
      'live_order_mutation_enabled':False,'stop_mutation_enabled':False,'target_mutation_enabled':False,
      'position_size_mutation_enabled':False,'production_effect':'NONE'}

def evaluate(snapshot:dict[str,Any]|None=None)->dict[str,Any]:
    s=snapshot or {}; pos=_pick(s,'position','open_position',default=s)
    if not isinstance(pos,dict) or not pos or not bool(pos.get('position_open',True)):
        return {'status':'FLAT','position_open':False,'action':'NO_ACTION','urgency':'NONE','remaining_edge_score':0.0,
          'recommendations':[],'advisory_only':True,'broker_effect':'NONE'}
    side=str(pos.get('side') or 'LONG').upper(); d=_direction(side) or 1
    entry=_num(pos.get('entry_price')); mark=_num(pos.get('mark_price') or pos.get('current_price')); stop=_num(pos.get('stop_price'))
    tp1=_num(pos.get('tp1') or pos.get('target_1')); tp2=_num(pos.get('tp2') or pos.get('target_2')); tp3=_num(pos.get('tp3') or pos.get('target_3'))
    qty=max(0.0,_num(pos.get('quantity'),1)); hold=_num(pos.get('time_in_trade_seconds'))
    initial_risk=abs(entry-stop) if entry and stop else max(abs(entry)*0.05,0.01)
    progress_r=d*(mark-entry)/initial_risk if entry and mark else 0.0
    pnl=d*(mark-entry)*qty*100 if entry and mark else _num(pos.get('unrealized_pnl'))
    ics=_num(_pick(s,'institutional_confluence_score','institutional_confluence.institutional_confluence_score','confluence_score'),50)
    pressure=_num(_pick(s,'institutional_pressure_score','pressure.institutional_pressure_score'),50)
    pconv=_num(_pick(s,'pressure_conviction','pressure.conviction'),50)
    msconf=_num(_pick(s,'market_state_confidence','market_state.confidence'),50)
    pqs=_num(_pick(s,'playbook_quality_score','playbook.playbook_quality_score'),50)
    structure=_num(_pick(s,'structure_alignment'),50)
    playbook_valid=bool(_pick(s,'playbook_valid','playbook.valid',default=True))
    state_valid=bool(_pick(s,'market_state_valid','market_state.valid',default=True))
    invalidated=not playbook_valid or not state_valid or bool(s.get('invalidation_triggered'))
    components={'institutional_confluence':ics,'institutional_pressure':pressure,'pressure_conviction':pconv,
      'market_state_confidence':msconf,'playbook_quality':pqs,'structure_alignment':structure}
    remaining=sum(components.values())/len(components)
    if invalidated: remaining*=0.25
    if progress_r < -0.75: remaining*=0.55
    if hold>1800: remaining*=0.85
    remaining=_clamp(remaining)
    recs=[]; action='HOLD'; urgency='NORMAL'
    if invalidated:
        action='EXIT'; urgency='HIGH'; recs.append({'type':'EXIT','reason':'Active playbook or market state is invalidated.','priority':1})
    elif progress_r<=-1.0:
        action='EXIT'; urgency='HIGH'; recs.append({'type':'EXIT','reason':'Price has reached or exceeded the planned risk unit.','priority':1})
    elif remaining<40:
        action='PROTECT'; urgency='HIGH'; recs.append({'type':'TIGHTEN_OR_EXIT','reason':'Remaining edge has deteriorated below 40.','priority':1})
    elif progress_r>=2.0:
        action='SCALE_AND_TRAIL'; urgency='MEDIUM'; recs += [
          {'type':'SCALE','reason':'Trade has reached at least 2R; protect realized opportunity.','priority':1},
          {'type':'TRAIL','reason':'Trail behind validated market structure rather than a fixed arbitrary distance.','priority':2}]
    elif progress_r>=1.0:
        action='PROTECT'; urgency='MEDIUM'; recs += [
          {'type':'BREAKEVEN','reason':'Trade has reached at least 1R with positive remaining edge.','priority':1},
          {'type':'PARTIAL_AT_TP1','reason':'Take the predefined partial only if TP1 is reached.','priority':2}]
    elif progress_r>=0.5 and remaining>=70:
        action='HOLD'; recs.append({'type':'HOLD','reason':'Edge remains strong and trade has not yet reached the first protection threshold.','priority':1})
    else:
        recs.append({'type':'HOLD_OR_EXIT_PER_STOP','reason':'Maintain the original plan; do not widen the stop.','priority':1})
    reached={'tp1':bool(tp1 and d*(mark-tp1)>=0),'tp2':bool(tp2 and d*(mark-tp2)>=0),'tp3':bool(tp3 and d*(mark-tp3)>=0)}
    return {'status':'READY','position_open':True,'symbol':pos.get('symbol','SPX'),'trade_id':str(pos.get('trade_id') or pos.get('id') or 'UNASSIGNED'),
      'side':side,'quantity':qty,'entry_price':entry or None,'mark_price':mark or None,'stop_price':stop or None,
      'unrealized_pnl':round(pnl,2),'progress_r':round(progress_r,3),'time_in_trade_seconds':round(hold,2),
      'remaining_edge_score':round(remaining,2),'action':action,'urgency':urgency,'recommendations':recs,
      'targets_reached':reached,'validity':{'playbook_valid':playbook_valid,'market_state_valid':state_valid,'invalidated':invalidated},
      'evidence_components':components,'advisory_only':True,'broker_effect':'NONE','orders_changed':False}

def record(snapshot:dict[str,Any],*,trade_id:str|None=None,symbol='SPX',observed_at:str|None=None,actor='SYSTEM'):
    init_db(); out=evaluate(snapshot); tid=str(trade_id or out.get('trade_id') or 'UNASSIGNED'); observed=observed_at or _now()
    with _conn() as c:r=c.execute('SELECT * FROM adaptive_trade_management_events WHERE trade_id=? AND observed_at=?',(tid,observed)).fetchone()
    if r:
        d=dict(r); d['payload']=json.loads(d.pop('payload_json')); return {'ok':True,'status':'IMMUTABLE_EXISTS','created':False,**d,'production_effect':'NONE'}
    payload={'snapshot':snapshot,'assessment':out}; ih=hashlib.sha256(_json(payload).encode()).hexdigest(); mid=str(uuid.uuid4()); created=_now()
    with _conn() as c:c.execute('INSERT INTO adaptive_trade_management_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(mid,tid,symbol,observed,out['action'],out['urgency'],out['remaining_edge_score'],_json(payload),SCHEMA_VERSION,VERSION,ih,created))
    gov.audit('CREATE_ADAPTIVE_TRADE_MANAGEMENT_EVENT','adaptive_trade_management',mid,new={'trade_id':tid,'action':out['action'],'integrity_hash':ih},actor=actor,explanation='Immutable advisory trade-management assessment')
    return {'ok':True,'status':'CREATED','created':True,'management_id':mid,'trade_id':tid,'symbol':symbol,'observed_at':observed,**out,'integrity_hash':ih,'created_at':created,'production_effect':'NONE'}

def history(trade_id:str|None=None,limit=100):
    init_db(); q='SELECT * FROM adaptive_trade_management_events WHERE 1=1'; a=[]
    if trade_id:q+=' AND trade_id=?';a.append(trade_id)
    q+=' ORDER BY observed_at DESC LIMIT ?';a.append(max(1,min(int(limit),1000)))
    with _conn() as c:rows=c.execute(q,a).fetchall()
    out=[]
    for r in rows:
        d=dict(r); d['payload']=json.loads(d.pop('payload_json')); out.append(d)
    return out

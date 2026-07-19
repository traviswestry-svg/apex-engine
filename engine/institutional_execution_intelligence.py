"""APEX 15.4: Institutional Execution Intelligence (IEI).

Offline, immutable trade execution analytics. Measures entry/exit efficiency,
slippage, stop behavior, hold duration, realized versus available profit, and
execution mistakes. It never places, changes, or routes broker orders.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, sqlite3, uuid
from typing import Any
from . import institutional_governance as gov

VERSION='15.0.15.4'; SCHEMA_VERSION='apex.iei.v1'

def _now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def _json(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def _load(v,d=None):
    try:return json.loads(v)
    except Exception:return [] if d==[] else ({} if d is None else d)
def _conn():
    c=sqlite3.connect(gov.DB_PATH); c.row_factory=sqlite3.Row; return c

def init_db():
    gov.init_db()
    with _conn() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS execution_intelligence_records(
          execution_id TEXT PRIMARY KEY, trade_id TEXT NOT NULL UNIQUE, symbol TEXT NOT NULL,
          side TEXT NOT NULL, quantity REAL NOT NULL, opened_at TEXT NOT NULL, closed_at TEXT NOT NULL,
          planned_entry REAL NOT NULL, actual_entry REAL NOT NULL, actual_exit REAL NOT NULL,
          stop_price REAL, best_price REAL, worst_price REAL, fees REAL NOT NULL,
          context_json TEXT NOT NULL, metrics_json TEXT NOT NULL, diagnostics_json TEXT NOT NULL,
          schema_version TEXT NOT NULL, engine_version TEXT NOT NULL, integrity_hash TEXT NOT NULL,
          created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_iei_time ON execution_intelligence_records(opened_at);
        CREATE TABLE IF NOT EXISTS execution_intelligence_analyses(
          analysis_id TEXT PRIMARY KEY, as_of TEXT NOT NULL, filter_json TEXT NOT NULL,
          sample_size INTEGER NOT NULL, metrics_json TEXT NOT NULL, diagnostics_json TEXT NOT NULL,
          schema_version TEXT NOT NULL, engine_version TEXT NOT NULL, integrity_hash TEXT NOT NULL,
          created_at TEXT NOT NULL);
        ''')
    return {'ok':True,'schema_version':SCHEMA_VERSION,'build_version':VERSION}

def _direction(side:str)->int: return 1 if str(side).upper() in {'LONG','BUY','CALL','BULLISH'} else -1

def evaluate_trade(*,side:str,quantity:float,planned_entry:float,actual_entry:float,actual_exit:float,
                   opened_at:str,closed_at:str,stop_price:float|None=None,best_price:float|None=None,
                   worst_price:float|None=None,fees:float=0.0,context:dict|None=None)->dict[str,Any]:
    d=_direction(side); q=max(float(quantity),0.0); pe=float(planned_entry); ae=float(actual_entry); ax=float(actual_exit)
    bp=float(best_price if best_price is not None else max(ae,ax) if d>0 else min(ae,ax))
    wp=float(worst_price if worst_price is not None else min(ae,ax) if d>0 else max(ae,ax))
    slippage_points=d*(ae-pe); realized_points=d*(ax-ae); available_points=max(0.0,d*(bp-ae)); adverse_points=max(0.0,-d*(wp-ae))
    gross=realized_points*q*100; net=gross-float(fees); max_available=available_points*q*100-float(fees)
    capture=100.0 if available_points<=0 and realized_points>=0 else (max(0.0,min(100.0,realized_points/available_points*100)) if available_points>0 else 0.0)
    stop_distance=abs(ae-float(stop_price)) if stop_price is not None else 0.0
    risk_r=stop_distance if stop_distance>0 else None
    realized_r=(realized_points/risk_r) if risk_r else None
    try:
        hold=max(0.0,(dt.datetime.fromisoformat(closed_at.replace('Z','+00:00'))-dt.datetime.fromisoformat(opened_at.replace('Z','+00:00'))).total_seconds())
    except Exception: hold=0.0
    mistakes=[]
    if slippage_points>0: mistakes.append('ADVERSE_ENTRY_SLIPPAGE')
    if available_points>0 and capture<35 and realized_points>0: mistakes.append('LOW_PROFIT_CAPTURE')
    if realized_points<0 and adverse_points>0 and stop_distance>0 and adverse_points>stop_distance*1.1: mistakes.append('STOP_OVERRUN')
    if hold>1800: mistakes.append('EXTENDED_HOLD')
    metrics={'entry_slippage_points':round(slippage_points,4),'realized_points':round(realized_points,4),'available_points':round(available_points,4),'adverse_excursion_points':round(adverse_points,4),'gross_pnl':round(gross,2),'net_pnl':round(net,2),'max_available_pnl':round(max_available,2),'profit_capture_pct':round(capture,2),'hold_seconds':round(hold,2),'realized_r':None if realized_r is None else round(realized_r,4),'entry_quality_score':round(max(0,100-min(100,max(0,slippage_points)*25)),2),'exit_quality_score':round(capture,2)}
    quality=round((metrics['entry_quality_score']+metrics['exit_quality_score'])/2,2)
    diagnostics={'execution_quality_score':quality,'mistakes':mistakes,'mistake_count':len(mistakes),'broker_action_taken':False,'live_order_mutation':False,'production_effect':'NONE'}
    return {'metrics':metrics,'diagnostics':diagnostics,'context':context or {}}

def record(*,trade_id:str,symbol='SPX',side='LONG',quantity=1,planned_entry:float,actual_entry:float,actual_exit:float,
           opened_at:str,closed_at:str,stop_price=None,best_price=None,worst_price=None,fees=0.0,context=None,actor='SYSTEM'):
    init_db()
    with _conn() as c:
        row=c.execute('SELECT * FROM execution_intelligence_records WHERE trade_id=?',(trade_id,)).fetchone()
    if row:return {'ok':True,'status':'IMMUTABLE_EXISTS','created':False,**_decode(dict(row)),'production_effect':'NONE'}
    out=evaluate_trade(side=side,quantity=quantity,planned_entry=planned_entry,actual_entry=actual_entry,actual_exit=actual_exit,opened_at=opened_at,closed_at=closed_at,stop_price=stop_price,best_price=best_price,worst_price=worst_price,fees=fees,context=context)
    payload={'trade_id':trade_id,'symbol':symbol,'side':side,'quantity':float(quantity),'opened_at':opened_at,'closed_at':closed_at,'planned_entry':float(planned_entry),'actual_entry':float(actual_entry),'actual_exit':float(actual_exit),'stop_price':stop_price,'best_price':best_price,'worst_price':worst_price,'fees':float(fees),'context':context or {},'metrics':out['metrics'],'diagnostics':out['diagnostics']}
    ih=hashlib.sha256(_json(payload).encode()).hexdigest(); eid=str(uuid.uuid4()); created=_now()
    with _conn() as c:c.execute('INSERT INTO execution_intelligence_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(eid,trade_id,symbol,side,float(quantity),opened_at,closed_at,float(planned_entry),float(actual_entry),float(actual_exit),stop_price,best_price,worst_price,float(fees),_json(context or {}),_json(out['metrics']),_json(out['diagnostics']),SCHEMA_VERSION,VERSION,ih,created))
    gov.audit('CREATE_EXECUTION_INTELLIGENCE_RECORD','execution_intelligence',eid,new={'trade_id':trade_id,'integrity_hash':ih},actor=actor,explanation='Immutable completed-trade execution analysis')
    return {'ok':True,'status':'CREATED','created':True,'execution_id':eid,**payload,'integrity_hash':ih,'created_at':created,'production_effect':'NONE'}

def _decode(d):
    d['context']=_load(d.pop('context_json')); d['metrics']=_load(d.pop('metrics_json')); d['diagnostics']=_load(d.pop('diagnostics_json')); return d

def records(limit=100,symbol=None):
    init_db(); q='SELECT * FROM execution_intelligence_records WHERE 1=1'; a=[]
    if symbol:q+=' AND symbol=?';a.append(symbol)
    q+=' ORDER BY opened_at DESC LIMIT ?';a.append(max(1,min(int(limit),1000)))
    with _conn() as c:return [_decode(dict(r)) for r in c.execute(q,a).fetchall()]

def analyze(*,symbol=None,as_of=None,persist=False,actor='SYSTEM'):
    rs=records(1000,symbol); rs=[r for r in rs if not as_of or r['closed_at']<=as_of]; n=len(rs)
    def avg(k): return round(sum(float(r['metrics'].get(k) or 0) for r in rs)/n,4) if n else 0.0
    wins=sum(1 for r in rs if float(r['metrics'].get('net_pnl') or 0)>0)
    metrics={'sample_size':n,'win_rate':round(100*wins/n,2) if n else 0.0,'net_pnl':round(sum(float(r['metrics'].get('net_pnl') or 0) for r in rs),2),'average_entry_slippage_points':avg('entry_slippage_points'),'average_profit_capture_pct':avg('profit_capture_pct'),'average_hold_seconds':avg('hold_seconds'),'average_execution_quality_score':round(sum(float(r['diagnostics'].get('execution_quality_score') or 0) for r in rs)/n,2) if n else 0.0,'total_execution_mistakes':sum(int(r['diagnostics'].get('mistake_count') or 0) for r in rs)}
    diagnostics={'status':'READY' if n>=10 else 'COLLECTING','minimum_research_sample':10,'broker_execution_changed':False,'live_feedback_enabled':False,'automatic_policy_update_enabled':False,'production_effect':'NONE'}
    out={'ok':True,'status':diagnostics['status'],'as_of':as_of or _now(),'filters':{'symbol':symbol},'metrics':metrics,'diagnostics':diagnostics}
    if persist:
        aid=str(uuid.uuid4()); created=_now(); ih=hashlib.sha256(_json(out).encode()).hexdigest()
        with _conn() as c:c.execute('INSERT INTO execution_intelligence_analyses VALUES(?,?,?,?,?,?,?,?,?,?)',(aid,out['as_of'],_json(out['filters']),n,_json(metrics),_json(diagnostics),SCHEMA_VERSION,VERSION,ih,created))
        gov.audit('CREATE_EXECUTION_INTELLIGENCE_ANALYSIS','execution_intelligence_analysis',aid,new={'sample_size':n,'integrity_hash':ih},actor=actor,explanation='Immutable offline execution intelligence analysis')
        out.update({'analysis_id':aid,'integrity_hash':ih,'created_at':created,'created':True})
    return out

def dashboard(symbol=None): return {'ok':True,'status':'READY','summary':analyze(symbol=symbol),'recent_trades':records(50,symbol),'safety':status()}
def status():
    init_db()
    with _conn() as c:
        r=c.execute('SELECT COUNT(*) n FROM execution_intelligence_records').fetchone()['n']; a=c.execute('SELECT COUNT(*) n FROM execution_intelligence_analyses').fetchone()['n']
    return {'status':'READY','schema_version':SCHEMA_VERSION,'build_version':VERSION,'record_count':r,'analysis_count':a,'offline_analytics_only':True,'broker_order_submission_enabled':False,'live_order_mutation_enabled':False,'automatic_policy_update_enabled':False,'production_effect':'NONE'}

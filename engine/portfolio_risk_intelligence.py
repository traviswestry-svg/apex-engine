"""APEX 16.3 Portfolio & Risk Intelligence.

Deterministic, read-only portfolio exposure and daily risk-governance engine.
It computes position heat, net Greeks, concentration, risk-budget utilization,
trade-frequency controls, and lockout state. It never submits or mutates orders.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, math, sqlite3, uuid
from typing import Any
from . import institutional_governance as gov

VERSION='16.3.16.3'; SCHEMA_VERSION='apex.portfolio_risk_intelligence.v1'
DEFAULT_POLICY={'max_daily_loss':1000.0,'max_risk_per_trade':2000.0,'max_trades_per_day':3,'max_position_heat_pct':35.0,'max_symbol_concentration_pct':100.0,'max_open_positions':3,'loss_lockout_count':2}

def _now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def _json(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def _conn():
    c=sqlite3.connect(gov.DB_PATH); c.row_factory=sqlite3.Row; return c
def _num(v,default=0.0):
    try:
        x=float(v); return x if math.isfinite(x) else default
    except Exception:return default
def _clamp(v,lo=0.0,hi=100.0): return max(lo,min(hi,float(v)))
def init_db():
    gov.init_db()
    with _conn() as c:c.executescript('''
    CREATE TABLE IF NOT EXISTS portfolio_risk_snapshots(
      risk_snapshot_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, observed_at TEXT NOT NULL,
      risk_state TEXT NOT NULL, risk_score REAL NOT NULL, payload_json TEXT NOT NULL,
      schema_version TEXT NOT NULL, engine_version TEXT NOT NULL, integrity_hash TEXT NOT NULL,
      created_at TEXT NOT NULL, UNIQUE(account_id,observed_at));
    CREATE INDEX IF NOT EXISTS idx_pri_account_time ON portfolio_risk_snapshots(account_id,observed_at);
    ''')
    return {'ok':True,'schema_version':SCHEMA_VERSION,'build_version':VERSION}
def status():
    init_db()
    with _conn() as c:n=c.execute('SELECT COUNT(*) n FROM portfolio_risk_snapshots').fetchone()['n']
    return {'status':'READY','engine':'PORTFOLIO_RISK_INTELLIGENCE','build_version':VERSION,'schema_version':SCHEMA_VERSION,
      'snapshot_count':n,'deterministic':True,'advisory_only':True,'future_information_allowed':False,
      'broker_order_submission_enabled':False,'live_order_mutation_enabled':False,'automatic_lockout_execution_enabled':False,
      'production_effect':'NONE','default_policy':DEFAULT_POLICY}
def _position(p):
    qty=max(0.0,_num(p.get('quantity'),1)); multiplier=max(1.0,_num(p.get('multiplier'),100)); mark=_num(p.get('mark_price') or p.get('current_price') or p.get('entry_price'))
    entry=_num(p.get('entry_price')); stop=_num(p.get('stop_price')); max_risk=_num(p.get('max_risk'))
    if max_risk<=0 and entry and stop:max_risk=abs(entry-stop)*qty*multiplier
    market_value=abs(mark*qty*multiplier)
    return {'position_id':str(p.get('position_id') or p.get('trade_id') or p.get('id') or 'UNASSIGNED'),'symbol':str(p.get('symbol') or 'UNKNOWN').upper(),
      'side':str(p.get('side') or 'LONG').upper(),'quantity':qty,'market_value':round(market_value,2),'max_risk':round(max_risk,2),
      'unrealized_pnl':round(_num(p.get('unrealized_pnl')),2),'delta':round(_num(p.get('delta'))*qty*multiplier,4),
      'gamma':round(_num(p.get('gamma'))*qty*multiplier,4),'theta':round(_num(p.get('theta'))*qty*multiplier,4),
      'vega':round(_num(p.get('vega'))*qty*multiplier,4)}
def evaluate(snapshot:dict[str,Any]|None=None)->dict[str,Any]:
    s=snapshot or {}; policy={**DEFAULT_POLICY,**(s.get('policy') or {})}; raw=s.get('positions') or s.get('open_positions') or []
    if isinstance(raw,dict):raw=[raw]
    positions=[_position(p) for p in raw if isinstance(p,dict) and bool(p.get('position_open',True))]
    equity=max(1.0,_num(s.get('account_equity') or s.get('net_liquidation'),60000)); realized=_num(s.get('realized_pnl_today')); unrealized=sum(p['unrealized_pnl'] for p in positions)
    daily_pnl=realized+unrealized; total_risk=sum(p['max_risk'] for p in positions); total_mv=sum(p['market_value'] for p in positions)
    heat_pct=100*total_risk/equity; trades=max(0,int(_num(s.get('trades_today')))); losses=max(0,int(_num(s.get('losses_today'))))
    by_symbol={}
    for p in positions:by_symbol[p['symbol']]=by_symbol.get(p['symbol'],0)+p['market_value']
    concentration=max((100*v/total_mv for v in by_symbol.values()),default=0.0)
    greeks={g:round(sum(p[g] for p in positions),4) for g in ('delta','gamma','theta','vega')}
    breaches=[]
    if daily_pnl<=-abs(_num(policy['max_daily_loss'])):breaches.append('MAX_DAILY_LOSS')
    if losses>=int(policy['loss_lockout_count']):breaches.append('LOSS_COUNT_LOCKOUT')
    if trades>=int(policy['max_trades_per_day']):breaches.append('TRADE_FREQUENCY_LIMIT')
    if len(positions)>int(policy['max_open_positions']):breaches.append('MAX_OPEN_POSITIONS')
    if heat_pct>_num(policy['max_position_heat_pct']):breaches.append('POSITION_HEAT_LIMIT')
    if concentration>_num(policy['max_symbol_concentration_pct']):breaches.append('CONCENTRATION_LIMIT')
    if any(p['max_risk']>_num(policy['max_risk_per_trade']) for p in positions):breaches.append('PER_TRADE_RISK_LIMIT')
    hard={'MAX_DAILY_LOSS','LOSS_COUNT_LOCKOUT','TRADE_FREQUENCY_LIMIT'}
    lockout=bool(hard.intersection(breaches)); risk_state='LOCKED_OUT' if lockout else ('BREACH' if breaches else ('ELEVATED' if heat_pct>=0.75*_num(policy['max_position_heat_pct']) else 'NORMAL'))
    utilization=max(100*abs(min(daily_pnl,0))/_num(policy['max_daily_loss']),100*heat_pct/_num(policy['max_position_heat_pct']),100*trades/max(1,int(policy['max_trades_per_day'])))
    risk_score=round(_clamp(100-utilization),2)
    permissions={'new_entries_allowed':not lockout and 'POSITION_HEAT_LIMIT' not in breaches and 'MAX_OPEN_POSITIONS' not in breaches,
      'add_to_position_allowed':not breaches,'risk_increase_allowed':not breaches,'risk_reduction_allowed':True,'close_positions_allowed':True}
    return {'status':'READY','risk_state':risk_state,'risk_score':risk_score,'lockout_recommended':lockout,'account_equity':round(equity,2),
      'daily_pnl':round(daily_pnl,2),'realized_pnl_today':round(realized,2),'unrealized_pnl':round(unrealized,2),
      'daily_loss_budget_remaining':round(max(0,_num(policy['max_daily_loss'])+daily_pnl),2),'position_heat_pct':round(heat_pct,2),
      'total_open_risk':round(total_risk,2),'open_position_count':len(positions),'trades_today':trades,'losses_today':losses,
      'symbol_concentration_pct':round(concentration,2),'net_greeks':greeks,'positions':positions,'breaches':breaches,
      'permissions':permissions,'policy':policy,'advisory_only':True,'broker_effect':'NONE','orders_changed':False}
def record(snapshot:dict[str,Any],*,account_id='PRIMARY',observed_at:str|None=None,actor='SYSTEM'):
    init_db(); out=evaluate(snapshot); observed=observed_at or _now()
    with _conn() as c:r=c.execute('SELECT * FROM portfolio_risk_snapshots WHERE account_id=? AND observed_at=?',(account_id,observed)).fetchone()
    if r:
        d=dict(r); d['payload']=json.loads(d.pop('payload_json')); return {'ok':True,'status':'IMMUTABLE_EXISTS','created':False,**d,'production_effect':'NONE'}
    payload={'snapshot':snapshot,'assessment':out}; ih=hashlib.sha256(_json(payload).encode()).hexdigest(); rid=str(uuid.uuid4()); created=_now()
    with _conn() as c:c.execute('INSERT INTO portfolio_risk_snapshots VALUES(?,?,?,?,?,?,?,?,?,?)',(rid,account_id,observed,out['risk_state'],out['risk_score'],_json(payload),SCHEMA_VERSION,VERSION,ih,created))
    gov.audit('CREATE_PORTFOLIO_RISK_SNAPSHOT','portfolio_risk_intelligence',rid,new={'account_id':account_id,'risk_state':out['risk_state'],'integrity_hash':ih},actor=actor,explanation='Immutable advisory portfolio risk assessment')
    return {'ok':True,'status':'CREATED','created':True,'risk_snapshot_id':rid,'account_id':account_id,'observed_at':observed,**out,'integrity_hash':ih,'created_at':created,'production_effect':'NONE'}
def history(account_id='PRIMARY',limit=100):
    init_db()
    with _conn() as c:rows=c.execute('SELECT * FROM portfolio_risk_snapshots WHERE account_id=? ORDER BY observed_at DESC LIMIT ?',(account_id,max(1,min(int(limit),1000)))).fetchall()
    out=[]
    for r in rows:
        d=dict(r); d['payload']=json.loads(d.pop('payload_json')); out.append(d)
    return out

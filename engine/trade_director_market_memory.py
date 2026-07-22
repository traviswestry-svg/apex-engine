"""APEX Trade Director Phase 12 — Institutional Intelligence & Market Memory.

Lazy, local-only analytics and persistence. No provider requests, background workers,
scanner activity, broker calls, or order transmission occur in this module.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Tuple

_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_memory_sessions (
 session_id TEXT PRIMARY KEY, session_date TEXT NOT NULL, captured_at TEXT NOT NULL,
 snapshot_json TEXT NOT NULL, outcome_json TEXT, source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_market_memory_date ON market_memory_sessions(session_date DESC);
CREATE TABLE IF NOT EXISTS market_memory_opportunities (
 opportunity_id TEXT PRIMARY KEY, session_date TEXT NOT NULL, captured_at TEXT NOT NULL,
 opportunity_json TEXT NOT NULL, outcome_json TEXT
);
"""

def _f(v: Any, d: float=0.0)->float:
    try: return float(v)
    except (TypeError, ValueError): return d

def _clamp(v: float, lo: float=0.0, hi: float=100.0)->float: return max(lo,min(hi,v))
def _now()->str: return dt.datetime.now(dt.timezone.utc).isoformat()
def memory_db_path()->str:
    p=os.getenv('APEX_MARKET_MEMORY_DB','').strip()
    if p: return p
    if os.path.isdir('/data') and os.access('/data',os.W_OK): return '/data/apex_market_memory.db'
    return os.path.join(os.getcwd(),'apex_market_memory.db')
def _connect()->sqlite3.Connection:
    p=memory_db_path(); parent=os.path.dirname(p)
    if parent: os.makedirs(parent,exist_ok=True)
    c=sqlite3.connect(p,timeout=3.0); c.row_factory=sqlite3.Row; c.executescript(_SCHEMA); return c

def _nested(d: Dict[str,Any], *paths: str, default: Any=None)->Any:
    for path in paths:
        cur: Any=d
        ok=True
        for part in path.split('.'):
            if not isinstance(cur,dict) or part not in cur: ok=False; break
            cur=cur[part]
        if ok and cur is not None: return cur
    return default

def build_market_snapshot(active: Optional[Dict[str,Any]], monitor: Optional[Dict[str,Any]], session: Optional[Dict[str,Any]]=None, now: Optional[dt.datetime]=None)->Dict[str,Any]:
    active=dict(active or {}); m=dict(monitor or {}); s=dict(session or m.get('session_intelligence') or {})
    now=now or dt.datetime.now()
    analysis=dict(m.get('institutional_analysis') or {})
    health=dict(m.get('health_engine') or {})
    policy=dict(m.get('management_policy') or {})
    flow=dict(m.get('flow_snapshot') or {})
    position=dict(m.get('position_intelligence') or {})
    regime=str(_nested(policy,'regime.name','regime',default='DATA_LIMITED')).upper()
    auction=str(_nested(analysis,'engines.auction.state','auction.state',default='UNKNOWN')).upper()
    vp=str(_nested(analysis,'engines.volume_profile.state','volume_profile.state',default='UNKNOWN')).upper()
    dealer=str(_nested(analysis,'engines.dealer_gamma.state','dealer_gamma.state',default='UNKNOWN')).upper()
    structure=str(_nested(analysis,'engines.market_structure.state','market_structure.state',default='UNKNOWN')).upper()
    expected=str(_nested(analysis,'engines.expected_path.state','expected_path.state',default='UNKNOWN')).upper()
    confidence=_f(m.get('confidence'),50); trade_health=_f(m.get('trade_health'),50)
    flow_score=_f(flow.get('flow_score') or flow.get('order_flow_score'),50)
    session_data=dict(s.get('session') or {})
    return {
      'session_date': now.date().isoformat(), 'captured_at': now.isoformat(),
      'ticker': active.get('ticker') or 'SPX', 'side': active.get('side'),
      'regime': regime, 'auction': auction, 'volume_profile': vp, 'dealer_gamma': dealer,
      'market_structure': structure, 'expected_path': expected,
      'flow_bias': str(flow.get('bias') or 'UNKNOWN').upper(), 'flow_score': round(flow_score,2),
      'confidence': round(confidence,2), 'trade_health': round(trade_health,2),
      'session_mode': str(session_data.get('mode') or 'OBSERVATION').upper(),
      'realized_pnl': _f(session_data.get('realized_pnl')), 'net_pnl': _f(session_data.get('net_pnl')),
      'recommendation': str(m.get('recommendation') or 'HOLD').upper(),
      'cross_asset_regime': str(_nested(m,'cross_asset_intelligence.regime',default='UNKNOWN')).upper(),
      'spx_confirmation_score': _f(_nested(m,'cross_asset_intelligence.spx_confirmation_score',default=50),50),
      'cross_asset_bias': str(_nested(m,'cross_asset_intelligence.cross_asset_bias',default='NEUTRAL')).upper(),
      'features_version':'13.0' if m.get('cross_asset_intelligence') else '12.0'
    }

def archive_session(snapshot: Dict[str,Any], outcome: Optional[Dict[str,Any]]=None, source: str='MANUAL')->Dict[str,Any]:
    raw=json.dumps(snapshot,sort_keys=True,default=str)
    sid='MM-'+hashlib.sha256((snapshot.get('session_date','')+raw).encode()).hexdigest()[:14].upper()
    with _connect() as c:
        c.execute("""INSERT INTO market_memory_sessions(session_id,session_date,captured_at,snapshot_json,outcome_json,source)
        VALUES(?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET snapshot_json=excluded.snapshot_json,outcome_json=COALESCE(excluded.outcome_json,market_memory_sessions.outcome_json),captured_at=excluded.captured_at""",
        (sid,str(snapshot.get('session_date') or '')[:10],str(snapshot.get('captured_at') or _now()),raw,json.dumps(outcome,default=str) if outcome else None,source))
    return {'session_id':sid,'snapshot':snapshot,'outcome':outcome,'source':source}

def memory_sessions(limit:int=250)->List[Dict[str,Any]]:
    limit=max(1,min(2000,int(limit)))
    with _connect() as c: rows=c.execute('SELECT * FROM market_memory_sessions ORDER BY session_date DESC,captured_at DESC LIMIT ?',(limit,)).fetchall()
    out=[]
    for r in rows:
        try: snap=json.loads(r['snapshot_json'] or '{}')
        except Exception: snap={}
        try: outcome=json.loads(r['outcome_json']) if r['outcome_json'] else None
        except Exception: outcome=None
        out.append({'session_id':r['session_id'],'session_date':r['session_date'],'captured_at':r['captured_at'],'snapshot':snap,'outcome':outcome,'source':r['source']})
    return out

def seed_from_trades(trades: Iterable[Dict[str,Any]])->List[Dict[str,Any]]:
    rows=[]
    for t in trades or []:
        p=dict(t.get('position') or {}); out=dict(t.get('outcome') or {})
        stamp=t.get('entered_at') or t.get('closed_at') or t.get('updated_at') or _now()
        snap={'session_date':str(stamp)[:10],'captured_at':str(stamp),'ticker':t.get('ticker') or p.get('ticker') or 'SPX','side':t.get('side') or p.get('side'),
          'regime':str(p.get('regime') or p.get('market_regime') or 'DATA_LIMITED').upper(),'auction':str(p.get('auction_state') or 'UNKNOWN').upper(),
          'volume_profile':str(p.get('volume_profile_state') or 'UNKNOWN').upper(),'dealer_gamma':str(p.get('dealer_state') or 'UNKNOWN').upper(),
          'market_structure':str(p.get('structure') or 'UNKNOWN').upper(),'expected_path':str(p.get('expected_path') or 'UNKNOWN').upper(),
          'flow_bias':str(p.get('flow_bias') or 'UNKNOWN').upper(),'flow_score':_f(p.get('flow_score'),50),'confidence':_f(p.get('confidence'),50),
          'trade_health':_f(p.get('trade_health'),50),'session_mode':str(p.get('session_mode') or 'UNKNOWN').upper(),
          'realized_pnl':_f(out.get('realized_pnl')),'net_pnl':_f(out.get('realized_pnl')),'recommendation':str(p.get('last_recommendation') or 'UNKNOWN').upper(),'features_version':'12.0-seed'}
        rows.append({'session_id':'TRADE-'+str(t.get('trade_id') or hashlib.md5(json.dumps(snap,sort_keys=True).encode()).hexdigest()[:10]),'session_date':snap['session_date'],'captured_at':snap['captured_at'],'snapshot':snap,'outcome':out,'source':'PHASE6_TRADE'})
    return rows

_CATEGORICAL=['regime','auction','volume_profile','dealer_gamma','market_structure','expected_path','flow_bias','session_mode']
_NUMERIC={'flow_score':15.0,'confidence':20.0,'trade_health':20.0}
def _similarity(a:Dict[str,Any],b:Dict[str,Any])->Tuple[float,List[str]]:
    parts=[]; evidence=[]
    for k in _CATEGORICAL:
        av=str(a.get(k) or 'UNKNOWN'); bv=str(b.get(k) or 'UNKNOWN')
        if av=='UNKNOWN' or bv=='UNKNOWN' or av=='DATA_LIMITED' or bv=='DATA_LIMITED': score=.45
        else: score=1.0 if av==bv else 0.0
        parts.append(score)
        if score==1.0: evidence.append(k.replace('_',' ')+' matched')
    for k,scale in _NUMERIC.items():
        score=max(0.0,1.0-abs(_f(a.get(k),50)-_f(b.get(k),50))/scale); parts.append(score)
    return round(100*sum(parts)/len(parts),1),evidence[:5]

def classify_playbook(s:Dict[str,Any])->str:
    r=str(s.get('regime') or '').upper(); a=str(s.get('auction') or '').upper(); e=str(s.get('expected_path') or '').upper(); f=str(s.get('flow_bias') or '').upper()
    if 'EXHAUST' in r: return 'OPENING_REVERSAL'
    if 'TREND' in r and ('UP' in e or 'CALL' in f or 'BULL' in f): return 'TREND_CONTINUATION'
    if 'TREND' in r and ('DOWN' in e or 'PUT' in f or 'BEAR' in f): return 'TREND_CONTINUATION'
    if 'BALANCED' in r or 'BALANCE' in a: return 'BALANCED_AUCTION'
    if 'SQUEEZE' in e or 'GAMMA' in r: return 'GAMMA_SQUEEZE'
    if 'FAILED' in e or 'REJECT' in a: return 'FAILED_BREAKOUT'
    return 'DATA_LIMITED'

def _playbooks(rows:List[Dict[str,Any]])->List[Dict[str,Any]]:
    g:Dict[str,List[Dict[str,Any]]]={}
    for row in rows: g.setdefault(classify_playbook(row['snapshot']),[]).append(row)
    out=[]
    for name,items in g.items():
        pnls=[_f((x.get('outcome') or {}).get('realized_pnl'),_f(x['snapshot'].get('realized_pnl'))) for x in items]
        known=[p for p in pnls if p!=0]; wins=[p for p in known if p>0]; losses=[p for p in known if p<0]
        out.append({'playbook':name,'samples':len(items),'scored_samples':len(known),'win_rate':round(100*len(wins)/len(known),1) if known else None,
                    'average_pnl':round(sum(known)/len(known),2) if known else None,'profit_factor':round(sum(wins)/abs(sum(losses)),2) if losses else None})
    return sorted(out,key=lambda x:(-x['samples'],x['playbook']))

def _probabilities(matches:List[Dict[str,Any]])->List[Dict[str,Any]]:
    buckets={'TREND_UP':0.0,'BALANCED_ROTATION':0.0,'TREND_DOWN':0.0,'REVERSAL_OR_FAILED_BREAK':0.0,'DATA_LIMITED':0.0}
    for m in matches:
        s=m['snapshot']; w=max(.01,m['similarity']/100)
        e=str(s.get('expected_path') or '').upper(); r=str(s.get('regime') or '').upper(); side=str(s.get('side') or '').upper()
        if 'BALANCE' in r: b='BALANCED_ROTATION'
        elif 'EXHAUST' in r or 'FAILED' in e or 'REVERS' in e: b='REVERSAL_OR_FAILED_BREAK'
        elif 'UP' in e or side=='CALL': b='TREND_UP'
        elif 'DOWN' in e or side=='PUT': b='TREND_DOWN'
        else: b='DATA_LIMITED'
        buckets[b]+=w
    total=sum(buckets.values()) or 1
    return [{'scenario':k,'probability':round(v/total*100,1)} for k,v in sorted(buckets.items(),key=lambda x:-x[1])]

def build_intelligence(snapshot:Dict[str,Any], archived:Iterable[Dict[str,Any]], trade_history:Iterable[Dict[str,Any]]=())->Dict[str,Any]:
    rows=list(archived or [])+seed_from_trades(trade_history)
    unique={}
    for r in rows: unique[r['session_id']]=r
    rows=list(unique.values())
    matches=[]
    for r in rows:
        if r['snapshot'].get('session_date')==snapshot.get('session_date') and r.get('source')!='PHASE6_TRADE': continue
        sim,evidence=_similarity(snapshot,r['snapshot'])
        matches.append({**r,'similarity':sim,'evidence':evidence})
    matches.sort(key=lambda x:(-x['similarity'],x['session_date']))
    top=matches[:5]
    probs=_probabilities(top)
    top_prob=probs[0] if probs else {'scenario':'DATA_LIMITED','probability':100}
    calibrated=_clamp(_f(snapshot.get('confidence'),50) * (0.65 + min(len(matches),30)/100))
    planner={'expected_session_type':top_prob['scenario'],'confidence':round(top_prob['probability'],1),
      'preferred_playbook':classify_playbook(snapshot),'risk_posture':'NORMAL' if top_prob['probability']>=50 and len(top)>=3 else 'REDUCED',
      'invalidation':['Regime changes materially','Flow reverses against expected path','Trade Health falls below 55'],
      'note':'Planning is similarity-based and must not be treated as a guarantee.'}
    return {'version':'PHASE_12','as_of':_now(),'memory_status':{'archived_sessions':len(rows),'matched_sessions':len(matches),'database':memory_db_path(),'learning_state':'ESTABLISHED' if len(rows)>=100 else 'CALIBRATING' if len(rows)>=30 else 'LEARNING'},
      'current_snapshot':snapshot,'historical_matches':top,'probability_distribution':probs,'playbook_library':_playbooks(rows),
      'confidence_calibration':{'raw_confidence':snapshot.get('confidence'),'calibrated_confidence':round(calibrated,1),'samples':len(matches),'status':'PROVISIONAL' if len(matches)<30 else 'ACTIVE'},
      'predictive_session_planner':planner,
      'knowledge_graph':{'nodes':['REGIME','AUCTION','VOLUME_PROFILE','DEALER_GAMMA','FLOW','STRUCTURE','PLAYBOOK','OUTCOME'],
                         'relationships_observed':len(rows)*8,'status':'FOUNDATION'},
      'safety_note':'Phase 12 is research and planning intelligence only. Phase 9 and Phase 10 remain authoritative for risk and execution.'}

def record_missed_opportunity(payload:Dict[str,Any])->Dict[str,Any]:
    captured=str(payload.get('captured_at') or _now()); day=str(payload.get('session_date') or captured[:10])
    oid='MO-'+hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()[:14].upper()
    with _connect() as c:
        c.execute('INSERT OR REPLACE INTO market_memory_opportunities(opportunity_id,session_date,captured_at,opportunity_json,outcome_json) VALUES(?,?,?,?,?)',
          (oid,day,captured,json.dumps(payload,default=str),None))
    return {'opportunity_id':oid,'session_date':day,'captured_at':captured,'opportunity':payload}

def missed_opportunities(limit:int=50)->List[Dict[str,Any]]:
    with _connect() as c: rows=c.execute('SELECT * FROM market_memory_opportunities ORDER BY captured_at DESC LIMIT ?',(max(1,min(250,int(limit))),)).fetchall()
    out=[]
    for r in rows:
        try: p=json.loads(r['opportunity_json']); o=json.loads(r['outcome_json']) if r['outcome_json'] else None
        except Exception: p={}; o=None
        out.append({'opportunity_id':r['opportunity_id'],'session_date':r['session_date'],'captured_at':r['captured_at'],'opportunity':p,'outcome':o})
    return out

"""APEX 16.0: Institutional Order Flow Intelligence 2.0.

Deterministic, evidence-backed institutional pressure model. The engine
normalizes independently observed flow, dealer, auction, liquidity, breadth,
and ES/SPX evidence into an Institutional Pressure Score (IPS). It is advisory
and read-only: no recommendation, confidence, risk, or broker mutation.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, math, sqlite3, uuid
from typing import Any
from . import institutional_governance as gov

VERSION='16.0.16.0'; SCHEMA_VERSION='apex.iofi.v2'
COMPONENT_WEIGHTS={
 'options_sweeps':0.16,'block_conviction':0.10,'dealer_hedging':0.16,
 'gamma_structure':0.12,'delta_exposure':0.08,'auction_imbalance':0.10,
 'volume_profile':0.08,'liquidity_pressure':0.07,'breadth_leadership':0.07,
 'es_spx_confirmation':0.06,
}

def _now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def _json(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def _load(v,d=None):
    try:return json.loads(v)
    except Exception:return {} if d is None else d
def _conn():
    c=sqlite3.connect(gov.DB_PATH); c.row_factory=sqlite3.Row; return c
def _num(v,default=0.0):
    try:
        x=float(v); return x if math.isfinite(x) else default
    except Exception:return default
def _clamp(v,lo=-100.0,hi=100.0): return max(lo,min(hi,float(v)))
def _get(s,*keys,default=0.0):
    for k in keys:
        cur=s
        ok=True
        for p in k.split('.'):
            if isinstance(cur,dict) and p in cur: cur=cur[p]
            else: ok=False; break
        if ok and cur is not None:return cur
    return default

def init_db():
    gov.init_db()
    with _conn() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS institutional_pressure_records(
          pressure_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, session_id TEXT NOT NULL,
          observed_at TEXT NOT NULL, bias TEXT NOT NULL, institutional_pressure_score REAL NOT NULL,
          conviction REAL NOT NULL, components_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
          conflicts_json TEXT NOT NULL, source_snapshot_json TEXT NOT NULL,
          schema_version TEXT NOT NULL, engine_version TEXT NOT NULL,
          integrity_hash TEXT NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(symbol,session_id,observed_at));
        CREATE INDEX IF NOT EXISTS idx_pressure_symbol_time ON institutional_pressure_records(symbol,observed_at);
        CREATE TABLE IF NOT EXISTS institutional_pressure_transitions(
          transition_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, session_id TEXT NOT NULL,
          transitioned_at TEXT NOT NULL, prior_bias TEXT NOT NULL, new_bias TEXT NOT NULL,
          prior_score REAL NOT NULL, new_score REAL NOT NULL, prior_pressure_id TEXT NOT NULL,
          new_pressure_id TEXT NOT NULL, integrity_hash TEXT NOT NULL, created_at TEXT NOT NULL);
        ''')
    return {'ok':True,'status':'READY','schema_version':SCHEMA_VERSION,'build_version':VERSION}

def _component_scores(s:dict[str,Any]):
    call=_num(_get(s,'call_sweep_premium','flow.call_sweep_premium','sweeps.calls'))
    put=_num(_get(s,'put_sweep_premium','flow.put_sweep_premium','sweeps.puts'))
    sweep=_clamp(100*(call-put)/(abs(call)+abs(put)+1e-9))
    bull_blocks=_num(_get(s,'bullish_block_premium','flow.bullish_blocks','blocks.bullish'))
    bear_blocks=_num(_get(s,'bearish_block_premium','flow.bearish_blocks','blocks.bearish'))
    blocks=_clamp(100*(bull_blocks-bear_blocks)/(abs(bull_blocks)+abs(bear_blocks)+1e-9))
    dealer=_clamp(_num(_get(s,'dealer_hedging_pressure','dealer.hedging_pressure','dealer_pressure')))
    gamma_raw=_num(_get(s,'gamma_pressure','gamma.structure_score','gamma_score'))
    flip_dist=_num(_get(s,'gamma_flip_distance_pct','gamma.flip_distance_pct'),999)
    gamma=_clamp(gamma_raw + (15 if 0 <= flip_dist <= .25 and dealer>0 else -15 if 0 <= flip_dist <= .25 and dealer<0 else 0))
    dex=_clamp(_num(_get(s,'delta_exposure_pressure','dealer.delta_pressure','dex_pressure')))
    auction=_clamp(_num(_get(s,'auction_imbalance','auction.imbalance_score','auction_pressure')))
    profile=_clamp(_num(_get(s,'volume_profile_imbalance','volume_profile.imbalance_score','profile_pressure')))
    liquidity=_clamp(_num(_get(s,'liquidity_pressure','order_book_pressure','liquidity.pressure')))
    breadth=_clamp(_num(_get(s,'breadth_pressure','breadth.score','sector_leadership')))
    es=_num(_get(s,'es_return_pct','es.return_pct','es_change_pct'))
    spx=_num(_get(s,'spx_return_pct','spx.return_pct','spx_change_pct'))
    es_spx=_clamp(((es+spx)/2)*250 if es*spx>=0 else -min(100,abs(es-spx)*300))
    return {'options_sweeps':round(sweep,2),'block_conviction':round(blocks,2),'dealer_hedging':round(dealer,2),'gamma_structure':round(gamma,2),'delta_exposure':round(dex,2),'auction_imbalance':round(auction,2),'volume_profile':round(profile,2),'liquidity_pressure':round(liquidity,2),'breadth_leadership':round(breadth,2),'es_spx_confirmation':round(es_spx,2)}

def evaluate(snapshot:dict[str,Any]|None):
    s=snapshot or {}; components=_component_scores(s)
    net=sum(components[k]*COMPONENT_WEIGHTS[k] for k in COMPONENT_WEIGHTS)
    coverage=sum(1 for k,v in components.items() if abs(v)>0)/len(components)
    dispersion=sum(abs(v-net) for v in components.values())/len(components)
    conviction=_clamp(abs(net)*(0.65+0.35*coverage)-0.15*dispersion,0,100)
    ips=round(50+net/2,2)
    if net>=25:bias='STRONG_BULLISH'
    elif net>=8:bias='BULLISH'
    elif net<=-25:bias='STRONG_BEARISH'
    elif net<=-8:bias='BEARISH'
    else:bias='NEUTRAL'
    ranked=sorted(({'component':k,'score':v,'weight':COMPONENT_WEIGHTS[k],'weighted_impact':round(v*COMPONENT_WEIGHTS[k],2)} for k,v in components.items()),key=lambda x:abs(x['weighted_impact']),reverse=True)
    evidence=[x for x in ranked if abs(x['score'])>=15]
    conflicts=[x for x in ranked if (net>0 and x['score']< -15) or (net<0 and x['score']>15)]
    return {'bias':bias,'institutional_pressure_score':ips,'net_pressure':round(net,2),'conviction':round(conviction,2),'coverage_pct':round(coverage*100,2),'components':components,'ranked_drivers':ranked,'evidence':evidence,'conflicts':conflicts,'safety':status()}

def record(snapshot:dict[str,Any]|None,*,symbol='SPX',session_id='',observed_at=None,actor='SYSTEM'):
    init_db(); observed_at=observed_at or _now(); session_id=session_id or observed_at[:10]; result=evaluate(snapshot)
    payload={'symbol':symbol,'session_id':session_id,'observed_at':observed_at,'result':result,'source_snapshot':snapshot or {}}
    ih=hashlib.sha256(_json(payload).encode()).hexdigest()
    with _conn() as c:r=c.execute('SELECT * FROM institutional_pressure_records WHERE symbol=? AND session_id=? AND observed_at=?',(symbol,session_id,observed_at)).fetchone()
    if r:return {'ok':True,'status':'IMMUTABLE_EXISTS','created':False,**_decode(dict(r)),'production_effect':'NONE'}
    pid=str(uuid.uuid4()); created=_now()
    with _conn() as c:
        prior=c.execute('SELECT * FROM institutional_pressure_records WHERE symbol=? AND session_id=? ORDER BY observed_at DESC LIMIT 1',(symbol,session_id)).fetchone()
        c.execute('INSERT INTO institutional_pressure_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(pid,symbol,session_id,observed_at,result['bias'],result['institutional_pressure_score'],result['conviction'],_json(result['components']),_json(result['evidence']),_json(result['conflicts']),_json(snapshot or {}),SCHEMA_VERSION,VERSION,ih,created))
        transition=None
        if prior and prior['bias']!=result['bias']:
            tid=str(uuid.uuid4()); tp={'symbol':symbol,'session_id':session_id,'transitioned_at':observed_at,'prior_bias':prior['bias'],'new_bias':result['bias'],'prior_score':prior['institutional_pressure_score'],'new_score':result['institutional_pressure_score'],'prior_pressure_id':prior['pressure_id'],'new_pressure_id':pid}; tih=hashlib.sha256(_json(tp).encode()).hexdigest()
            c.execute('INSERT INTO institutional_pressure_transitions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(tid,symbol,session_id,observed_at,prior['bias'],result['bias'],prior['institutional_pressure_score'],result['institutional_pressure_score'],prior['pressure_id'],pid,tih,created)); transition={**tp,'transition_id':tid,'integrity_hash':tih}
    gov.audit('CREATE_INSTITUTIONAL_PRESSURE','institutional_pressure',pid,new={'bias':result['bias'],'score':result['institutional_pressure_score'],'integrity_hash':ih},actor=actor,explanation='Immutable deterministic institutional pressure snapshot')
    return {'ok':True,'status':'CREATED','created':True,'pressure_id':pid,**payload,**result,'integrity_hash':ih,'created_at':created,'transition':transition,'production_effect':'NONE'}

def _decode(d):
    d['components']=_load(d.pop('components_json')); d['evidence']=_load(d.pop('evidence_json'),[]); d['conflicts']=_load(d.pop('conflicts_json'),[]); d['source_snapshot']=_load(d.pop('source_snapshot_json')); return d

def current(symbol='SPX',as_of=None):
    init_db(); q='SELECT * FROM institutional_pressure_records WHERE symbol=?'; a=[symbol]
    if as_of:q+=' AND observed_at<=?';a.append(as_of)
    q+=' ORDER BY observed_at DESC LIMIT 1'
    with _conn() as c:r=c.execute(q,a).fetchone()
    return {'ok':False,'status':'UNAVAILABLE'} if not r else {'ok':True,'status':'READY',**_decode(dict(r))}
def history(symbol='SPX',limit=100):
    init_db()
    with _conn() as c:return [_decode(dict(r)) for r in c.execute('SELECT * FROM institutional_pressure_records WHERE symbol=? ORDER BY observed_at DESC LIMIT ?',(symbol,max(1,min(int(limit),1000)))).fetchall()]
def transitions(symbol='SPX',limit=100):
    init_db()
    with _conn() as c:return [dict(r) for r in c.execute('SELECT * FROM institutional_pressure_transitions WHERE symbol=? ORDER BY transitioned_at DESC LIMIT ?',(symbol,max(1,min(int(limit),1000)))).fetchall()]
def dashboard(symbol='SPX'):
    cur=current(symbol); return {'ok':True,'status':'READY' if cur.get('ok') else 'COLLECTING','current':cur if cur.get('ok') else None,'history':history(symbol,25),'transitions':transitions(symbol,25),'safety':status()}
def status():
    init_db(); return {'status':'READY','engine':'INSTITUTIONAL_ORDER_FLOW_INTELLIGENCE_2','build_version':VERSION,'schema_version':SCHEMA_VERSION,'deterministic':True,'future_information_allowed':False,'recommendation_mutation_enabled':False,'confidence_mutation_enabled':False,'broker_order_submission_enabled':False,'production_effect':'NONE','components':list(COMPONENT_WEIGHTS)}

"""APEX 16.4 Explainable Intelligence Assistant.

Deterministic evidence-grounded explanation layer. It answers a bounded set of
institutional questions using only supplied/current APEX evidence and immutable
records. No free-form model inference, recommendation mutation, or broker effect.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, sqlite3, uuid
from typing import Any
from . import institutional_governance as gov

VERSION='16.4.16.4'; SCHEMA_VERSION='apex.explainable_intelligence.v1'
SUPPORTED_INTENTS=('WHY_CONFIDENCE','WHY_ACTION','WHAT_CHANGED','WHY_INVALIDATED','SIMILAR_SESSIONS','EVIDENCE_SUMMARY')

def _now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def _json(v): return json.dumps(v,sort_keys=True,separators=(',',':'),default=str)
def _conn():
    c=sqlite3.connect(gov.DB_PATH); c.row_factory=sqlite3.Row; return c

def init_db():
    gov.init_db()
    with _conn() as c:c.executescript('''
    CREATE TABLE IF NOT EXISTS explainable_intelligence_interactions(
      interaction_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, observed_at TEXT NOT NULL,
      intent TEXT NOT NULL, question TEXT NOT NULL, answer_json TEXT NOT NULL,
      evidence_json TEXT NOT NULL, schema_version TEXT NOT NULL, engine_version TEXT NOT NULL,
      integrity_hash TEXT NOT NULL, created_at TEXT NOT NULL,
      UNIQUE(symbol,observed_at,intent,question));
    CREATE INDEX IF NOT EXISTS idx_eia_symbol_time ON explainable_intelligence_interactions(symbol,observed_at);
    ''')
    return {'ok':True,'schema_version':SCHEMA_VERSION,'build_version':VERSION}

def status():
    init_db()
    with _conn() as c:n=c.execute('SELECT COUNT(*) n FROM explainable_intelligence_interactions').fetchone()['n']
    return {'status':'READY','engine':'EXPLAINABLE_INTELLIGENCE_ASSISTANT','build_version':VERSION,
      'schema_version':SCHEMA_VERSION,'interaction_count':n,'supported_intents':SUPPORTED_INTENTS,
      'deterministic':True,'evidence_grounded_only':True,'free_form_generation_enabled':False,
      'future_information_allowed':False,'recommendation_mutation_enabled':False,
      'confidence_mutation_enabled':False,'broker_order_submission_enabled':False,'production_effect':'NONE'}

def classify_intent(question:str)->str:
    q=' '.join(str(question or '').lower().split())
    if 'similar' in q or 'like this' in q:return 'SIMILAR_SESSIONS'
    if 'invalid' in q or 'no longer valid' in q:return 'WHY_INVALIDATED'
    if 'what changed' in q or 'last ' in q or 'since ' in q:return 'WHAT_CHANGED'
    if 'confidence' in q or 'conviction' in q or 'confluence' in q:return 'WHY_CONFIDENCE'
    if 'why' in q and any(x in q for x in ('action','directive','calls','puts','enter','exit','hold','stand')):return 'WHY_ACTION'
    return 'EVIDENCE_SUMMARY'

def _get(d:dict,*paths,default=None):
    for path in paths:
        cur=d; ok=True
        for p in path.split('.'):
            if isinstance(cur,dict) and p in cur:cur=cur[p]
            else:ok=False; break
        if ok and cur is not None:return cur
    return default

def _evidence(snapshot:dict[str,Any])->list[dict[str,Any]]:
    rows=[]
    def add(source,metric,value,meaning):
        if value is not None and value!='':rows.append({'source':source,'metric':metric,'value':value,'meaning':meaning})
    add('MISSION_CONTROL','institutional_confluence_score',_get(snapshot,'institutional_confluence.institutional_confluence_score'),'Cross-engine alignment quality')
    add('MISSION_CONTROL','setup_grade',_get(snapshot,'institutional_confluence.grade'),'Current setup quality grade')
    add('ORDER_FLOW','institutional_pressure_score',_get(snapshot,'institutional_pressure.institutional_pressure_score','institutional_pressure.result.institutional_pressure_score'),'Institutional directional pressure')
    add('ORDER_FLOW','pressure_bias',_get(snapshot,'institutional_pressure.bias','institutional_pressure.result.bias'),'Institutional pressure direction')
    add('ORDER_FLOW','pressure_conviction',_get(snapshot,'institutional_pressure.conviction','institutional_pressure.result.conviction'),'Agreement and strength of order-flow evidence')
    add('MARKET_STATE','active_state',_get(snapshot,'market_state.active_state','market_state.state_name'),'Current institutional market state')
    add('MARKET_STATE','confidence',_get(snapshot,'market_state.confidence','market_state.state_confidence'),'Market-state classification confidence')
    add('MARKET_STATE','stability',_get(snapshot,'market_state.stability','market_state.stability_index'),'Market-state persistence')
    add('PLAYBOOK','active_playbook',_get(snapshot,'playbook.active_playbook','playbook.playbook_name'),'Highest-ranked active institutional playbook')
    add('PLAYBOOK','direction',_get(snapshot,'playbook.direction'),'Playbook direction')
    add('PLAYBOOK','quality',_get(snapshot,'playbook.playbook_quality_score','playbook.quality_score'),'Playbook evidence quality')
    add('TRADE_DIRECTOR','action',_get(snapshot,'trade_director.action','trade_director.recommendation'),'Current trade directive')
    add('TRADE_DIRECTOR','confidence',_get(snapshot,'trade_director.confidence','decision_confidence'),'Decision confidence')
    add('TRADE_MANAGEMENT','action',_get(snapshot,'adaptive_trade_management.action'),'Current advisory management action')
    add('TRADE_MANAGEMENT','remaining_edge',_get(snapshot,'adaptive_trade_management.remaining_edge_score'),'Estimated remaining institutional edge')
    add('RISK','risk_state',_get(snapshot,'portfolio_risk.risk_state'),'Current portfolio risk state')
    add('RISK','breaches',_get(snapshot,'portfolio_risk.breaches'),'Active risk-policy breaches')
    return rows

def explain(question:str,snapshot:dict[str,Any]|None=None,previous_snapshot:dict[str,Any]|None=None,similar_sessions:list|None=None)->dict[str,Any]:
    s=snapshot or {}; prev=previous_snapshot or {}; intent=classify_intent(question); ev=_evidence(s)
    facts={x['metric']:x['value'] for x in ev}; reasons=[]; answer=''
    if intent=='WHY_CONFIDENCE':
        comps=_get(s,'institutional_confluence.components',default=[]) or []
        ranked=sorted([c for c in comps if c.get('available')],key=lambda x:float(x.get('weighted') or 0),reverse=True)
        reasons=[f"{c.get('name')}={c.get('score')}" for c in ranked[:4]]
        answer=f"Confidence is primarily explained by {', '.join(reasons) if reasons else 'the available mission-control evidence'}. The current confluence score is {facts.get('institutional_confluence_score','unavailable')} with grade {facts.get('setup_grade','unavailable')}."
    elif intent=='WHY_ACTION':
        action=facts.get('action','WAIT'); reasons=[f"pressure bias={facts.get('pressure_bias','unavailable')}",f"market state={facts.get('active_state','unavailable')}",f"playbook={facts.get('active_playbook','unavailable')}",f"risk state={facts.get('risk_state','unavailable')}"]
        answer=f"The current directive is {action}. It is supported by " + ', '.join(reasons) + "."
    elif intent=='WHY_INVALIDATED':
        inv=_get(s,'playbook.invalidation','playbook.invalidation_conditions','adaptive_trade_management.reason',default='Evidence Not Available')
        reasons=[str(inv),f"remaining edge={facts.get('remaining_edge','unavailable')}",f"market state={facts.get('active_state','unavailable')}"]
        answer='The thesis is considered invalidated when the documented playbook or market-state conditions fail. Current evidence: '+', '.join(reasons)+'.'
    elif intent=='WHAT_CHANGED':
        old={x['metric']:x['value'] for x in _evidence(prev)}; changes=[]
        for k,v in facts.items():
            if k in old and old[k]!=v:changes.append({'metric':k,'from':old[k],'to':v})
        reasons=[f"{x['metric']}: {x['from']} → {x['to']}" for x in changes[:8]]
        answer='Detected changes: '+('; '.join(reasons) if reasons else 'no comparable evidence changed or a previous snapshot was not supplied.')
    elif intent=='SIMILAR_SESSIONS':
        sims=list(similar_sessions or [])[:10]; reasons=[str(x.get('session_id') or x.get('id') or 'UNKNOWN') for x in sims if isinstance(x,dict)]
        answer=f"Found {len(sims)} supplied comparable sessions. Similarity results are descriptive and do not alter the live recommendation."
    else:
        reasons=[f"{x['source']}.{x['metric']}={x['value']}" for x in ev[:8]]
        answer='Current evidence summary: '+('; '.join(reasons) if reasons else 'Evidence Not Available.')
    citations=[{'evidence_id':hashlib.sha256(_json(x).encode()).hexdigest()[:16],**x} for x in ev]
    return {'status':'ANSWERED','intent':intent,'question':question,'answer':answer,'reasons':reasons,
      'citations':citations,'similar_sessions':list(similar_sessions or [])[:10] if intent=='SIMILAR_SESSIONS' else [],
      'evidence_available':bool(ev),'evidence_only':True,'no_hallucination_fallback':'Evidence Not Available',
      'recommendation_changed':False,'confidence_changed':False,'broker_effect':'NONE'}

def record(question:str,snapshot:dict[str,Any],*,symbol='SPX',observed_at=None,previous_snapshot=None,similar_sessions=None,actor='SYSTEM'):
    init_db(); observed=observed_at or _now(); intent=classify_intent(question); out=explain(question,snapshot,previous_snapshot,similar_sessions)
    with _conn() as c:r=c.execute('SELECT * FROM explainable_intelligence_interactions WHERE symbol=? AND observed_at=? AND intent=? AND question=?',(symbol,observed,intent,question)).fetchone()
    if r:
        d=dict(r); d['answer']=json.loads(d.pop('answer_json')); d['evidence']=json.loads(d.pop('evidence_json')); return {'ok':True,'status':'IMMUTABLE_EXISTS','created':False,**d,'production_effect':'NONE'}
    evidence={'snapshot':snapshot,'previous_snapshot':previous_snapshot or {},'similar_sessions':similar_sessions or []}; ih=hashlib.sha256(_json({'answer':out,'evidence':evidence}).encode()).hexdigest(); iid=str(uuid.uuid4()); created=_now()
    with _conn() as c:c.execute('INSERT INTO explainable_intelligence_interactions VALUES(?,?,?,?,?,?,?,?,?,?,?)',(iid,symbol,observed,intent,question,_json(out),_json(evidence),SCHEMA_VERSION,VERSION,ih,created))
    gov.audit('CREATE_EXPLAINABLE_INTELLIGENCE_INTERACTION','explainable_intelligence_assistant',iid,new={'symbol':symbol,'intent':intent,'integrity_hash':ih},actor=actor,explanation='Immutable evidence-grounded explanation')
    return {'ok':True,'status':'CREATED','created':True,'interaction_id':iid,'symbol':symbol,'observed_at':observed,**out,'integrity_hash':ih,'created_at':created,'production_effect':'NONE'}

def history(symbol='SPX',limit=100):
    init_db()
    with _conn() as c:rows=c.execute('SELECT * FROM explainable_intelligence_interactions WHERE symbol=? ORDER BY observed_at DESC LIMIT ?',(symbol,max(1,min(int(limit),1000)))).fetchall()
    out=[]
    for r in rows:
        d=dict(r); d['answer']=json.loads(d.pop('answer_json')); d['evidence']=json.loads(d.pop('evidence_json')); out.append(d)
    return out

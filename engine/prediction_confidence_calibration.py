"""APEX 15.3: Prediction and Confidence Calibration Engine (PCCE).

Offline, outcome-linked calibration research. It measures whether frozen decision
confidence corresponds to observed success rates. It never mutates production
confidence and cannot promote calibration changes without existing governance.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, math, sqlite3, uuid
from typing import Any
from . import institutional_governance as gov

VERSION='15.0.15.3'; SCHEMA_VERSION='apex.pcce.v1'

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
        CREATE TABLE IF NOT EXISTS calibration_observations(
          observation_id TEXT PRIMARY KEY, prediction_id TEXT NOT NULL UNIQUE,
          symbol TEXT NOT NULL, predicted_at TEXT NOT NULL, outcome_at TEXT NOT NULL,
          confidence REAL NOT NULL, outcome INTEGER NOT NULL, segment_json TEXT NOT NULL,
          source_json TEXT NOT NULL, integrity_hash TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_cal_obs_time ON calibration_observations(predicted_at);
        CREATE TABLE IF NOT EXISTS confidence_calibration_analyses(
          analysis_id TEXT PRIMARY KEY, as_of TEXT NOT NULL, filter_json TEXT NOT NULL,
          sample_size INTEGER NOT NULL, metrics_json TEXT NOT NULL, bins_json TEXT NOT NULL,
          diagnostics_json TEXT NOT NULL, schema_version TEXT NOT NULL, engine_version TEXT NOT NULL,
          integrity_hash TEXT NOT NULL, created_at TEXT NOT NULL);
        ''')
    return {'ok':True,'schema_version':SCHEMA_VERSION,'build_version':VERSION}

def ingest(prediction_id:str, confidence:float, outcome:bool|int, *, symbol='SPX', predicted_at='', outcome_at='', segment=None, source=None, actor='SYSTEM'):
    init_db(); p=max(0.0,min(100.0,float(confidence))); y=1 if bool(outcome) else 0
    predicted_at=predicted_at or _now(); outcome_at=outcome_at or _now(); segment=segment or {}; source=source or {}
    with _conn() as c:
        row=c.execute('SELECT * FROM calibration_observations WHERE prediction_id=?',(prediction_id,)).fetchone()
    if row:return {'ok':True,'status':'IMMUTABLE_EXISTS','created':False,**dict(row),'production_effect':'NONE'}
    payload={'prediction_id':prediction_id,'symbol':symbol,'predicted_at':predicted_at,'outcome_at':outcome_at,'confidence':p,'outcome':y,'segment':segment,'source':source}
    ih=hashlib.sha256(_json(payload).encode()).hexdigest(); oid=str(uuid.uuid4()); created=_now()
    with _conn() as c:c.execute('INSERT INTO calibration_observations VALUES(?,?,?,?,?,?,?,?,?,?,?)',(oid,prediction_id,symbol,predicted_at,outcome_at,p,y,_json(segment),_json(source),ih,created))
    gov.audit('INGEST_CALIBRATION_OBSERVATION','calibration_observation',oid,new={'prediction_id':prediction_id,'integrity_hash':ih},actor=actor,explanation='Immutable completed-outcome calibration observation')
    return {'ok':True,'status':'CREATED','created':True,'observation_id':oid,**payload,'integrity_hash':ih,'created_at':created,'production_effect':'NONE'}

def _rows(as_of=None,symbol=None):
    init_db(); q='SELECT * FROM calibration_observations WHERE 1=1'; a=[]
    if as_of:q+=' AND outcome_at<=?'; a.append(as_of)
    if symbol:q+=' AND symbol=?'; a.append(symbol)
    q+=' ORDER BY predicted_at'
    with _conn() as c:return [dict(x) for x in c.execute(q,a).fetchall()]

def analyze(*,as_of=None,symbol=None,bin_width=10,persist=False,actor='SYSTEM'):
    as_of=as_of or _now(); rows=_rows(as_of,symbol); n=len(rows); bw=max(5,min(25,int(bin_width)))
    bins=[]
    for lo in range(0,100,bw):
        hi=min(100,lo+bw); xs=[r for r in rows if lo <= float(r['confidence']) < hi or (hi==100 and float(r['confidence'])==100)]
        if not xs: continue
        avg=sum(float(r['confidence']) for r in xs)/len(xs); actual=100*sum(int(r['outcome']) for r in xs)/len(xs)
        bins.append({'lower':lo,'upper':hi,'sample_size':len(xs),'mean_predicted':round(avg,2),'observed_success_rate':round(actual,2),'calibration_gap':round(actual-avg,2)})
    if n:
        probs=[float(r['confidence'])/100 for r in rows]; ys=[int(r['outcome']) for r in rows]
        brier=sum((p-y)**2 for p,y in zip(probs,ys))/n
        accuracy=sum(ys)/n; mean_conf=sum(probs)/n
        ece=sum((b['sample_size']/n)*abs(b['observed_success_rate']-b['mean_predicted'])/100 for b in bins)
        mce=max([abs(b['calibration_gap'])/100 for b in bins] or [0])
        logloss=-sum(y*math.log(max(p,1e-12))+(1-y)*math.log(max(1-p,1e-12)) for p,y in zip(probs,ys))/n
    else:brier=accuracy=mean_conf=ece=mce=logloss=0
    metrics={'sample_size':n,'observed_success_rate':round(accuracy*100,2),'mean_confidence':round(mean_conf*100,2),'confidence_bias':round((mean_conf-accuracy)*100,2),'brier_score':round(brier,6),'expected_calibration_error':round(ece,6),'maximum_calibration_error':round(mce,6),'log_loss':round(logloss,6)}
    diagnostics={'status':'READY' if n>=30 else 'COLLECTING','minimum_research_sample':30,'overconfident':metrics['confidence_bias']>2,'underconfident':metrics['confidence_bias']<-2,'production_confidence_changed':False,'promotion_required':True,'historical_outcomes_used_in_live_decisions':False}
    out={'ok':True,'status':diagnostics['status'],'as_of':as_of,'filters':{'symbol':symbol,'bin_width':bw},'metrics':metrics,'reliability_bins':bins,'diagnostics':diagnostics,'production_effect':'NONE'}
    if persist:
        raw=_json(out); ih=hashlib.sha256(raw.encode()).hexdigest(); aid=str(uuid.uuid4()); created=_now()
        with _conn() as c:c.execute('INSERT INTO confidence_calibration_analyses VALUES(?,?,?,?,?,?,?,?,?,?,?)',(aid,as_of,_json(out['filters']),n,_json(metrics),_json(bins),_json(diagnostics),SCHEMA_VERSION,VERSION,ih,created))
        gov.audit('CREATE_CONFIDENCE_CALIBRATION_ANALYSIS','confidence_calibration',aid,new={'sample_size':n,'integrity_hash':ih},actor=actor,explanation='Immutable offline confidence calibration analysis')
        out.update({'analysis_id':aid,'integrity_hash':ih,'created_at':created,'created':True})
    return out

def analyses(limit=100):
    init_db()
    with _conn() as c: rows=c.execute('SELECT * FROM confidence_calibration_analyses ORDER BY created_at DESC LIMIT ?',(max(1,min(int(limit),1000)),)).fetchall()
    out=[]
    for r in rows:
        d=dict(r); d['filters']=_load(d.pop('filter_json')); d['metrics']=_load(d.pop('metrics_json')); d['reliability_bins']=_load(d.pop('bins_json'),[]); d['diagnostics']=_load(d.pop('diagnostics_json')); out.append(d)
    return out

def dashboard(symbol=None):
    latest=analyze(symbol=symbol,persist=False)
    return {'ok':True,'status':latest['status'],'current_analysis':latest,'recent_analyses':analyses(20),'safety':status()}

def status():
    init_db()
    with _conn() as c:
        o=c.execute('SELECT COUNT(*) n FROM calibration_observations').fetchone()['n']; a=c.execute('SELECT COUNT(*) n FROM confidence_calibration_analyses').fetchone()['n']
    return {'status':'READY','schema_version':SCHEMA_VERSION,'build_version':VERSION,'observation_count':o,'analysis_count':a,'offline_research_only':True,'production_confidence_mutation_enabled':False,'automatic_promotion_enabled':False,'future_information_allowed_in_live_decisions':False,'production_effect':'NONE'}

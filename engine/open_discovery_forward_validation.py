"""APEX 69.10.34 — Open Discovery Shadow Candidate Forward Validation & Structural Evidence Capture.

Prospectively freezes exact decision-time structural evidence for RTH OPEN_DISCOVERY
abstentions and marks only the first observation in an anchor-horizon sequence as the
69.10.33 persistence=ONE shadow candidate.  The shadow label is observational only:
it cannot alter NO_TRADE, thresholds, calibration, learning eligibility, or execution.
Historical structural fields are never reconstructed.
"""
from __future__ import annotations
import hashlib, json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping
from .canonical_market_calendar import classify as classify_market_session
from .decision_outcome_attribution import DEFAULT_DB, _availability
from .canonical_persistence import connection as canonical_connection

VERSION="69.10.34"
SCHEMA_VERSION="apex.open_discovery_forward_validation.v1"
HORIZON_SECONDS=300
STRUCTURAL_KEYS={
 "range_intelligence","unified_structural_map","reversal_timing_intelligence",
 "expected_session_range","immediate_reaction_zones","intermediate_targets",
 "expansion_targets","regime_pivot","reaction_zones","destination_magnets",
 "session_path_scenarios","reversal_path","gamma_evidence","gamma_regime",
 "market_state","institutional_intelligence","multi_horizon_transition",
 "flow_state","flow","decision_authority","institutional_decision_object",
}
_SCHEMA="""
CREATE TABLE IF NOT EXISTS open_discovery_shadow_forward(
 decision_id TEXT PRIMARY KEY,
 captured_at TEXT NOT NULL,
 session_date_et TEXT NOT NULL,
 ticker TEXT NOT NULL,
 direction TEXT NOT NULL,
 action TEXT,
 confidence REAL,
 anchor_id TEXT NOT NULL,
 persistence_ordinal INTEGER NOT NULL,
 shadow_status TEXT NOT NULL,
 structural_evidence_json TEXT NOT NULL,
 structural_evidence_sha256 TEXT NOT NULL,
 calendar_json TEXT NOT NULL,
 schema_version TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_odsf_anchor ON open_discovery_shadow_forward(anchor_id,captured_at);
CREATE INDEX IF NOT EXISTS idx_odsf_session ON open_discovery_shadow_forward(session_date_et,captured_at);
"""

def ensure_schema(conn): conn.executescript(_SCHEMA)
def _dt(v): return datetime.fromisoformat(str(v).replace("Z","+00:00"))
def _stable(v): return json.dumps(v,default=str,separators=(",",":"),sort_keys=True)
def _anchor_id(ticker,direction,at): return "odsf_"+hashlib.sha256(f"{ticker}|{direction}|{at}".encode()).hexdigest()[:20]

def _extract_structural(snapshot: Mapping[str,Any]) -> Dict[str,Any]:
    """Freeze exact matching subtrees with source paths; never infer missing fields."""
    found={}
    def walk(v,path="",depth=0):
        if depth>9: return
        if isinstance(v,Mapping):
            for k,item in v.items():
                p=f"{path}.{k}" if path else str(k)
                if str(k) in STRUCTURAL_KEYS:
                    found[p]=item
                # Keep walking because nested canonical fields can coexist.
                walk(item,p,depth+1)
        elif isinstance(v,(list,tuple)):
            for i,item in enumerate(list(v)[:50]): walk(item,f"{path}[{i}]",depth+1)
    walk(snapshot)
    return {"source":"DECISION_TIME_SNAPSHOT","fields":found,"field_paths":sorted(found),
            "structural_fields_available":bool(found),"reconstructed":False}

def capture_forward(conn, decision_id:str, observed_at:str, snapshot:Mapping[str,Any]) -> bool:
    """Idempotent contemporaneous capture. Safe to call from evidence_pipeline writer."""
    cal=classify_market_session(observed_at)
    if not cal.get("rth_eligible") or cal.get("session_phase")!="OPEN_DISCOVERY": return False
    direction=str(snapshot.get("direction") or "").upper()
    action=str(snapshot.get("action") or snapshot.get("decision_state") or "").upper()
    entry=snapshot.get("entry_reference") if snapshot.get("entry_reference") is not None else snapshot.get("entry_price")
    if direction not in {"BULLISH","BEARISH"} or entry is None: return False
    # Match 68.6 abstention semantics without importing its private classifier.
    if bool(snapshot.get("learning_eligible")) and action not in {"NO_TRADE","STAND_DOWN","WATCH","WATCH_ONLY","ABSTAIN","NONE"}: return False
    ensure_schema(conn)
    ticker=str(snapshot.get("ticker") or "SPX").upper(); when=_dt(observed_at)
    previous=conn.execute("""SELECT anchor_id,captured_at,persistence_ordinal FROM open_discovery_shadow_forward
        WHERE ticker=? AND direction=? AND session_date_et=? ORDER BY captured_at DESC LIMIT 1""",
        (ticker,direction,str(cal.get("session_date")))).fetchone()
    if previous and (when-_dt(previous["captured_at"])).total_seconds()<=HORIZON_SECONDS:
        anchor=str(previous["anchor_id"]); ordinal=int(previous["persistence_ordinal"])+1
    else:
        anchor=_anchor_id(ticker,direction,observed_at); ordinal=1
    structural=_extract_structural(snapshot); payload=_stable(structural)
    status="SHADOW_ELIGIBLE_CANDIDATE" if ordinal==1 else "SHADOW_CONTROL_PERSISTENT"
    before=conn.total_changes
    conn.execute("""INSERT OR IGNORE INTO open_discovery_shadow_forward(
      decision_id,captured_at,session_date_et,ticker,direction,action,confidence,anchor_id,persistence_ordinal,
      shadow_status,structural_evidence_json,structural_evidence_sha256,calendar_json,schema_version)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(decision_id,observed_at,str(cal.get("session_date")),ticker,direction,action,
      snapshot.get("confidence"),anchor,ordinal,status,payload,hashlib.sha256(payload.encode()).hexdigest(),_stable(cal),SCHEMA_VERSION))
    return conn.total_changes>before

def _read(path=DEFAULT_DB):
    av=_availability(path)
    if av.get("status")!="READY": return av,[]
    with canonical_connection(path,read_only=True,timeout=4.0,wal=False,heal=False) as conn:
        exists=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='open_discovery_shadow_forward'").fetchone()
        if not exists: return av,[]
        rows=conn.execute("""SELECT f.*,a.status AS outcome_status,a.missed_opportunity,a.protective_abstention,
          a.directional_move,a.mfe,a.mae FROM open_discovery_shadow_forward f
          LEFT JOIN decision_effectiveness_attribution a ON a.decision_id=f.decision_id ORDER BY f.captured_at""").fetchall()
    return av,[dict(r) for r in rows]

def summary(path: str|Path=DEFAULT_DB)->Dict[str,Any]:
    av,rows=_read(path); candidates=[r for r in rows if r["shadow_status"]=="SHADOW_ELIGIBLE_CANDIDATE"]
    graded=[r for r in candidates if r.get("outcome_status")=="GRADED"]
    missed=sum(bool(r.get("missed_opportunity")) for r in graded); protective=sum(bool(r.get("protective_abstention")) for r in graded)
    sessions=sorted({r["session_date_et"] for r in candidates})
    structural=sum(bool(json.loads(r["structural_evidence_json"]).get("structural_fields_available")) for r in candidates)
    target=30
    return {"ok":not av.get("degraded",False),"version":VERSION,"schema_version":SCHEMA_VERSION,**av,
      "status":"READY" if av.get("status")=="READY" else av.get("status"),"execution_authority":False,
      "forward_population":{"captured_rows":len(rows),"candidate_clusters":len(candidates),"graded_candidates":len(graded),
        "missed_candidates":missed,"protective_candidates":protective,"candidate_missed_rate_pct":round(100*missed/len(graded),2) if graded else None,
        "independent_session_dates":len(sessions),"forward_target_clusters":target,"target_remaining":max(0,target-len(candidates)),
        "structural_evidence_captured":structural},
      "candidate_definition":{"session":"RTH_OPEN_DISCOVERY_0930_1000_ET","historical_hypothesis":"PERSISTENCE_ONE",
        "prospective_rule":"FIRST_OBSERVATION_IN_TICKER_DIRECTION_ANCHOR_HORIZON","anchor_horizon_seconds":HORIZON_SECONDS},
      "governance":{"observational_only":True,"prospective_capture_only":True,"historical_structural_reconstruction":False,
        "canonical_no_trade_unchanged":True,"shadow_label_has_no_decision_authority":True,"outcomes_not_used_at_capture":True,
        "changes_trade_decisions":False,"changes_thresholds":False,"changes_learning_eligibility":False,"feeds_calibration_automatically":False,
        "automatic_promotion":False,"automatic_execution":False,"automatic_order_submission":False,"human_review_required_for_policy_change":True}}

def detail(path: str|Path=DEFAULT_DB,limit:int=500)->Dict[str,Any]:
    av,rows=_read(path); items=[]
    for r in reversed(rows):
        x={k:v for k,v in r.items() if k not in {"structural_evidence_json","calendar_json"}}
        x["structural_evidence"]=json.loads(r["structural_evidence_json"]); x["calendar"]=json.loads(r["calendar_json"])
        # Outcome is shown for validation only; it was not available to capture-time labeling.
        x["canonical_mfe"]=max(0.0,float(r["mfe"])) if r.get("mfe") is not None else None
        x["canonical_mae"]=min(0.0,float(r["mae"])) if r.get("mae") is not None else None
        items.append(x)
    return {"ok":not av.get("degraded",False),"version":VERSION,"schema_version":SCHEMA_VERSION,**av,"items":items[:max(1,min(int(limit),2000))],"execution_authority":False}

"""APEX 15.2: Institutional Playbook Engine (IPE).

Deterministically recognizes governed SPX playbooks from a decision-time snapshot
and immutable IMSE context. IPE is advisory/read-only and never mutates a trade
recommendation, decision confidence, risk, or execution state.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import uuid
from typing import Any

from . import institutional_governance as gov
from . import institutional_market_state_engine as imse

VERSION = "15.0.15.2"
SCHEMA_VERSION = "apex.ipe.v1"

PLAYBOOK_LIBRARY: tuple[dict[str, Any], ...] = (
    {"id":"OPENING_DRIVE_CONTINUATION","name":"Opening Drive Continuation","family":"TREND","states":["TREND_AUCTION","GAMMA_EXPANSION","INSTITUTIONAL_ACCUMULATION"],"directional":True,"invalidation":["Loss of opening range","VWAP failure","Breadth reversal"]},
    {"id":"TREND_PULLBACK","name":"Trend Pullback","family":"TREND","states":["TREND_AUCTION","GAMMA_EXPANSION"],"directional":True,"invalidation":["Trend structure break","VWAP loss","Momentum divergence"]},
    {"id":"TREND_ACCELERATION","name":"Trend Acceleration","family":"TREND","states":["TREND_AUCTION","HIGH_VOLATILITY_EXPANSION","GAMMA_EXPANSION"],"directional":True,"invalidation":["Expansion failure","Breadth collapse"]},
    {"id":"VWAP_CONTINUATION","name":"VWAP Continuation","family":"TREND","states":["TREND_AUCTION","INSTITUTIONAL_ACCUMULATION","INSTITUTIONAL_DISTRIBUTION"],"directional":True,"invalidation":["Confirmed VWAP loss","Flow reversal"]},
    {"id":"VALUE_ACCEPTANCE","name":"Value Acceptance","family":"AUCTION","states":["BALANCED_AUCTION","DOUBLE_DISTRIBUTION"],"directional":False,"invalidation":["Sustained trade outside accepted value"]},
    {"id":"VALUE_REJECTION","name":"Value Rejection","family":"AUCTION","states":["FAILED_AUCTION","BALANCED_AUCTION"],"directional":True,"invalidation":["Acceptance beyond rejected value"]},
    {"id":"LVN_REJECTION","name":"LVN Rejection","family":"AUCTION","states":["FAILED_AUCTION","BALANCED_AUCTION"],"directional":True,"invalidation":["LVN acceptance","Volume migration through level"]},
    {"id":"HVN_ROTATION","name":"HVN Rotation","family":"AUCTION","states":["BALANCED_AUCTION","GAMMA_PIN"],"directional":False,"invalidation":["Value-area breakout","Gamma expansion"]},
    {"id":"POC_MIGRATION","name":"POC Migration","family":"AUCTION","states":["TREND_AUCTION","DOUBLE_DISTRIBUTION"],"directional":True,"invalidation":["POC migration stalls or reverses"]},
    {"id":"FAILED_AUCTION_REVERSAL","name":"Failed Auction Reversal","family":"REVERSAL","states":["FAILED_AUCTION","GAMMA_TRANSITION"],"directional":True,"invalidation":["Re-entry into failed extension"]},
    {"id":"GAMMA_PIN_ROTATION","name":"Gamma Pin Rotation","family":"GAMMA","states":["GAMMA_PIN","BALANCED_AUCTION","LOW_VOLATILITY_COMPRESSION"],"directional":False,"invalidation":["Break from gamma anchor","Volatility expansion"]},
    {"id":"GAMMA_EXPANSION_BREAKOUT","name":"Gamma Expansion Breakout","family":"GAMMA","states":["GAMMA_EXPANSION","HIGH_VOLATILITY_EXPANSION","TREND_AUCTION"],"directional":True,"invalidation":["Return inside breakout range","Dealer pressure reversal"]},
    {"id":"GAMMA_FLIP_REVERSAL","name":"Gamma Flip Reversal","family":"GAMMA","states":["GAMMA_TRANSITION","FAILED_AUCTION"],"directional":True,"invalidation":["Failure to hold gamma flip"]},
    {"id":"COMPRESSION_BREAKOUT","name":"Compression Breakout","family":"VOLATILITY","states":["LOW_VOLATILITY_COMPRESSION","GAMMA_TRANSITION"],"directional":True,"invalidation":["Breakout returns to compression range"]},
    {"id":"VOLATILITY_EXPANSION","name":"Volatility Expansion","family":"VOLATILITY","states":["HIGH_VOLATILITY_EXPANSION","GAMMA_EXPANSION"],"directional":True,"invalidation":["ATR contraction","Range failure"]},
    {"id":"ATR_EXHAUSTION","name":"ATR Exhaustion","family":"REVERSAL","states":["HIGH_VOLATILITY_EXPANSION","THIN_LIQUIDITY"],"directional":True,"invalidation":["Fresh range expansion with participation"]},
    {"id":"FLOW_CONTINUATION","name":"Institutional Flow Continuation","family":"FLOW","states":["INSTITUTIONAL_ACCUMULATION","INSTITUTIONAL_DISTRIBUTION","TREND_AUCTION"],"directional":True,"invalidation":["Flow polarity reversal","Breadth divergence"]},
    {"id":"OPENING_REVERSAL","name":"Opening Reversal","family":"REVERSAL","states":["FAILED_AUCTION","GAMMA_TRANSITION"],"directional":True,"invalidation":["Opening extreme reclaimed"]},
    {"id":"FAILED_BREAKOUT","name":"Failed Breakout","family":"REVERSAL","states":["FAILED_AUCTION","BALANCED_AUCTION"],"directional":True,"invalidation":["Acceptance above failed breakout"]},
    {"id":"FAILED_BREAKDOWN","name":"Failed Breakdown","family":"REVERSAL","states":["FAILED_AUCTION","BALANCED_AUCTION"],"directional":True,"invalidation":["Acceptance below failed breakdown"]},
)


def _now() -> str: return dt.datetime.now(dt.timezone.utc).isoformat()
def _json(v: Any) -> str: return json.dumps(v, sort_keys=True, separators=(",", ":"), default=str)
def _load(v: Any, default: Any = None) -> Any:
    if v in (None, ""): return {} if default is None else default
    try: return json.loads(v)
    except Exception: return {} if default is None else default

def _conn():
    c=sqlite3.connect(gov.DB_PATH); c.row_factory=sqlite3.Row; c.execute("PRAGMA foreign_keys=ON"); return c

def init_db() -> dict[str, Any]:
    gov.init_db(); imse.init_db()
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS institutional_playbook_records(
          playbook_record_id TEXT PRIMARY KEY,
          symbol TEXT NOT NULL,
          session_id TEXT NOT NULL,
          observed_at TEXT NOT NULL,
          market_state_id TEXT,
          active_playbook TEXT NOT NULL,
          active_playbook_name TEXT NOT NULL,
          direction TEXT NOT NULL,
          playbook_quality_score REAL NOT NULL,
          state_compatibility REAL NOT NULL,
          candidates_json TEXT NOT NULL,
          evidence_json TEXT NOT NULL,
          invalidation_json TEXT NOT NULL,
          source_snapshot_json TEXT NOT NULL,
          schema_version TEXT NOT NULL,
          engine_version TEXT NOT NULL,
          integrity_hash TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(symbol,session_id,observed_at)
        );
        CREATE INDEX IF NOT EXISTS idx_ipe_symbol_time ON institutional_playbook_records(symbol,observed_at);
        CREATE TABLE IF NOT EXISTS institutional_playbook_transitions(
          transition_id TEXT PRIMARY KEY,
          symbol TEXT NOT NULL,
          session_id TEXT NOT NULL,
          from_playbook TEXT,
          to_playbook TEXT NOT NULL,
          transition_at TEXT NOT NULL,
          prior_playbook_record_id TEXT,
          playbook_record_id TEXT NOT NULL,
          quality_delta REAL NOT NULL,
          integrity_hash TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(symbol,session_id,playbook_record_id)
        );
        CREATE TABLE IF NOT EXISTS institutional_playbook_outcomes(
          outcome_id TEXT PRIMARY KEY,
          playbook_record_id TEXT NOT NULL UNIQUE,
          outcome_at TEXT NOT NULL,
          won INTEGER,
          realized_r REAL,
          duration_minutes REAL,
          metadata_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        """)
    return {"ok":True,"schema_version":SCHEMA_VERSION,"build_version":VERSION}

def _num(d: dict[str, Any], *keys: str, default: float=0.0) -> float:
    for k in keys:
        try:
            if d.get(k) is not None: return float(d[k])
        except Exception: pass
    return default

def _flag(d: dict[str, Any], *keys: str) -> bool:
    for k in keys:
        v=d.get(k)
        if isinstance(v,bool): return v
        if str(v).upper() in {"TRUE","YES","ON","BULLISH","BEARISH","RISING","FALLING","EXPANDING"}: return True
    return False

def _direction(s: dict[str, Any]) -> str:
    bias=_num(s,"directional_bias","flow_bias","breadth","trend_direction")
    txt=str(s.get("direction") or s.get("bias") or "").upper()
    if txt in {"CALLS","CALL","BULLISH","LONG","UP"} or bias>5: return "BULLISH"
    if txt in {"PUTS","PUT","BEARISH","SHORT","DOWN"} or bias<-5: return "BEARISH"
    return "NEUTRAL"

def _state_payload(snapshot: dict[str, Any], market_state: dict[str, Any] | None, symbol: str, observed_at: str | None) -> dict[str, Any]:
    if market_state and market_state.get("active_state"): return market_state
    if observed_at:
        prior=imse.at_or_before(observed_at,symbol)
        if prior.get("ok"): return prior
    classified=imse.classify(snapshot)
    return {"market_state_id":None,**classified,"integrity_hash":None,"derived_for_preview":True}

def evaluate(snapshot: dict[str, Any], *, market_state: dict[str, Any] | None=None, symbol: str="SPX", observed_at: str | None=None) -> dict[str, Any]:
    """Evaluate only supplied decision-time data and an at-or-before IMSE state."""
    s=dict(snapshot or {}); ms=_state_payload(s,market_state,symbol,observed_at)
    active_state=str(ms.get("active_state") or "UNAVAILABLE")
    secondary={str(x.get("state")):float(x.get("confidence") or 0) for x in ms.get("secondary_states") or []}
    state_scores={active_state:float(ms.get("active_confidence") or 0),**secondary}
    trend=abs(_num(s,"trend_strength","adx","directional_strength")); balance=_num(s,"balance_score","auction_balance",default=50)
    atr=_num(s,"atr_pct","atr_percent","volatility_pct"); flow=abs(_num(s,"flow_bias","institutional_flow","premium_bias")); breadth=abs(_num(s,"breadth","breadth_score"))
    opening=_flag(s,"opening_drive","opening_range_break","orb_breakout"); pullback=_flag(s,"pullback_confirmed","trend_pullback")
    vwap=_flag(s,"vwap_hold","vwap_reclaim"); failed=_flag(s,"failed_auction","failed_breakout","failed_breakdown")
    compression=_flag(s,"compression","volatility_compression") or atr<1.0
    poc=_flag(s,"poc_migration"); lvn=_flag(s,"lvn_rejection"); hvn=_flag(s,"hvn_rotation")
    direction=_direction(s)
    candidates=[]
    for pb in PLAYBOOK_LIBRARY:
        compat=max([state_scores.get(st,0) for st in pb["states"]] or [0])
        evidence=0.0; matched=[]
        pid=pb["id"]
        checks=[
            ("OPENING" in pid and opening,20,"opening structure"),
            ("PULLBACK" in pid and pullback,20,"confirmed pullback"),
            ("VWAP" in pid and vwap,18,"VWAP confirmation"),
            ("FAILED" in pid and failed,22,"failed auction/break"),
            ("COMPRESSION" in pid and compression,20,"volatility compression"),
            ("POC" in pid and poc,20,"POC migration"),
            ("LVN" in pid and lvn,22,"LVN rejection"),
            ("HVN" in pid and hvn,22,"HVN rotation"),
            (pb["family"]=="TREND",min(20,trend/4),"trend strength"),
            (pb["family"]=="AUCTION",min(20,balance/5),"auction balance"),
            (pb["family"]=="GAMMA",min(20,float(ms.get("active_confidence") or 0)/5),"gamma state"),
            (pb["family"]=="VOLATILITY",min(20,atr*8),"volatility state"),
            (pb["family"]=="FLOW",min(20,(flow+breadth)/8),"institutional participation"),
        ]
        for cond,pts,label in checks:
            if cond: evidence+=float(pts); matched.append(label)
        completeness=min(100,30+len(matched)*12)
        conflict=15 if pb["directional"] and direction=="NEUTRAL" else 0
        pqs=round(max(0,min(100,compat*0.55+evidence*0.30+completeness*0.15-conflict)),2)
        candidates.append({"playbook_id":pid,"name":pb["name"],"family":pb["family"],"direction":direction if pb["directional"] else "NEUTRAL","playbook_quality_score":pqs,"state_compatibility":round(compat,2),"matched_evidence":matched,"invalidation":pb["invalidation"]})
    candidates.sort(key=lambda x:(-x["playbook_quality_score"],-x["state_compatibility"],x["playbook_id"]))
    active=candidates[0]
    return {"active_playbook":active["playbook_id"],"active_playbook_name":active["name"],"direction":active["direction"],"playbook_quality_score":active["playbook_quality_score"],"state_compatibility":active["state_compatibility"],"ranked_candidates":candidates[:8],"evidence":active["matched_evidence"],"invalidation":active["invalidation"],"market_state":{"market_state_id":ms.get("market_state_id"),"active_state":active_state,"active_confidence":ms.get("active_confidence"),"stability_index":ms.get("stability_index"),"integrity_hash":ms.get("integrity_hash")},"future_information_used":False,"historical_outcomes_used_in_live_selection":False}

def _row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    d=dict(row)
    for k in ("candidates_json","evidence_json","invalidation_json","source_snapshot_json"):
        if k in d: d[k[:-5]]=_load(d.pop(k),[] if k!="source_snapshot_json" else {})
    return d

def record(snapshot: dict[str, Any], *, market_state: dict[str, Any] | None=None, symbol: str="SPX", session_id: str="", observed_at: str | None=None, actor: str="SYSTEM") -> dict[str, Any]:
    init_db(); observed_at=observed_at or str(snapshot.get("observed_at") or _now()); session_id=session_id or str(snapshot.get("session_id") or observed_at[:10])
    result=evaluate(snapshot,market_state=market_state,symbol=symbol,observed_at=observed_at)
    with _conn() as c:
        existing=c.execute("SELECT * FROM institutional_playbook_records WHERE symbol=? AND session_id=? AND observed_at=?",(symbol,session_id,observed_at)).fetchone()
    if existing: return {"ok":True,"status":"IMMUTABLE_EXISTS","created":False,**_row(existing),"production_effect":"NONE"}
    payload={"symbol":symbol,"session_id":session_id,"observed_at":observed_at,**result,"source_snapshot":snapshot,"schema_version":SCHEMA_VERSION,"engine_version":VERSION}
    ih=hashlib.sha256(_json(payload).encode()).hexdigest(); rid=str(uuid.uuid4()); created=_now()
    with _conn() as c:
        c.execute("INSERT INTO institutional_playbook_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(rid,symbol,session_id,observed_at,result["market_state"].get("market_state_id"),result["active_playbook"],result["active_playbook_name"],result["direction"],result["playbook_quality_score"],result["state_compatibility"],_json(result["ranked_candidates"]),_json(result["evidence"]),_json(result["invalidation"]),_json(snapshot),SCHEMA_VERSION,VERSION,ih,created))
        prior=c.execute("SELECT * FROM institutional_playbook_records WHERE symbol=? AND session_id=? AND playbook_record_id<>? AND observed_at<=? ORDER BY observed_at DESC LIMIT 1",(symbol,session_id,rid,observed_at)).fetchone()
        if prior is None or prior["active_playbook"]!=result["active_playbook"]:
            tp={"symbol":symbol,"session_id":session_id,"from_playbook":prior["active_playbook"] if prior else None,"to_playbook":result["active_playbook"],"transition_at":observed_at,"prior_playbook_record_id":prior["playbook_record_id"] if prior else None,"playbook_record_id":rid,"quality_delta":round(result["playbook_quality_score"]-(prior["playbook_quality_score"] if prior else 0),2)}
            tih=hashlib.sha256(_json(tp).encode()).hexdigest()
            c.execute("INSERT INTO institutional_playbook_transitions VALUES(?,?,?,?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),symbol,session_id,tp["from_playbook"],tp["to_playbook"],observed_at,tp["prior_playbook_record_id"],rid,tp["quality_delta"],tih,created))
    gov.audit("RECORD_INSTITUTIONAL_PLAYBOOK","institutional_playbook",rid,new={"active_playbook":result["active_playbook"],"integrity_hash":ih},actor=actor,explanation="Immutable decision-time playbook recognition recorded")
    return {"ok":True,"status":"CREATED","created":True,"playbook_record_id":rid,**payload,"integrity_hash":ih,"created_at":created,"production_effect":"NONE"}

def at_or_before(observed_at: str, symbol: str="SPX") -> dict[str, Any]:
    init_db()
    with _conn() as c: row=c.execute("SELECT * FROM institutional_playbook_records WHERE symbol=? AND observed_at<=? ORDER BY observed_at DESC LIMIT 1",(symbol,observed_at)).fetchone()
    return {"ok":False,"status":"UNAVAILABLE"} if not row else {"ok":True,"status":"READY",**_row(row),"production_effect":"NONE"}

def current(symbol: str="SPX") -> dict[str, Any]:
    init_db()
    with _conn() as c: row=c.execute("SELECT * FROM institutional_playbook_records WHERE symbol=? ORDER BY observed_at DESC LIMIT 1",(symbol,)).fetchone()
    return {"ok":False,"status":"UNAVAILABLE"} if not row else {"ok":True,"status":"READY",**_row(row),"production_effect":"NONE"}

def history(symbol: str="SPX",limit: int=100) -> list[dict[str, Any]]:
    init_db()
    with _conn() as c: rows=c.execute("SELECT * FROM institutional_playbook_records WHERE symbol=? ORDER BY observed_at DESC LIMIT ?",(symbol,max(1,min(int(limit),1000)))).fetchall()
    return [_row(x) for x in rows]

def transitions(symbol: str="SPX",limit: int=100) -> list[dict[str, Any]]:
    init_db()
    with _conn() as c: rows=c.execute("SELECT * FROM institutional_playbook_transitions WHERE symbol=? ORDER BY transition_at DESC LIMIT ?",(symbol,max(1,min(int(limit),1000)))).fetchall()
    return [dict(x) for x in rows]

def statistics(playbook_id: str | None=None) -> dict[str, Any]:
    """Outcome analytics are descriptive and never feed live playbook selection."""
    init_db(); where=""; params=[]
    if playbook_id: where="WHERE p.active_playbook=?"; params=[playbook_id]
    with _conn() as c:
        rows=c.execute(f"SELECT p.active_playbook,p.active_playbook_name,o.won,o.realized_r,o.duration_minutes FROM institutional_playbook_records p LEFT JOIN institutional_playbook_outcomes o ON o.playbook_record_id=p.playbook_record_id {where}",params).fetchall()
    groups={}
    for r in rows:
        g=groups.setdefault(r["active_playbook"],{"playbook_id":r["active_playbook"],"name":r["active_playbook_name"],"recognized":0,"completed":0,"wins":0,"r_values":[],"durations":[]})
        g["recognized"]+=1
        if r["won"] is not None:
            g["completed"]+=1; g["wins"]+=int(r["won"]); g["r_values"].append(float(r["realized_r"] or 0)); g["durations"].append(float(r["duration_minutes"] or 0))
    out=[]
    for g in groups.values():
        n=g.pop("completed"); rs=g.pop("r_values"); ds=g.pop("durations")
        g.update({"completed":n,"win_rate":round(g["wins"]*100/n,2) if n else None,"average_r":round(sum(rs)/n,3) if n else None,"average_duration_minutes":round(sum(ds)/n,2) if n else None,"selection_feedback_enabled":False}); out.append(g)
    return {"ok":True,"status":"READY","statistics":sorted(out,key=lambda x:x["playbook_id"]),"historical_outcomes_used_in_live_selection":False,"production_effect":"NONE"}

def dashboard(symbol: str="SPX") -> dict[str, Any]:
    return {"ok":True,"status":"READY","current":current(symbol) if current(symbol).get("ok") else None,"transitions":transitions(symbol,25),"statistics":statistics()["statistics"],"library":[{"playbook_id":x["id"],"name":x["name"],"family":x["family"],"compatible_states":x["states"]} for x in PLAYBOOK_LIBRARY],"production_effect":"NONE"}

def status() -> dict[str, Any]:
    init_db()
    with _conn() as c:
        records=c.execute("SELECT COUNT(*) FROM institutional_playbook_records").fetchone()[0]; trans=c.execute("SELECT COUNT(*) FROM institutional_playbook_transitions").fetchone()[0]
    return {"status":"READY","schema_version":SCHEMA_VERSION,"build_version":VERSION,"playbook_count":len(PLAYBOOK_LIBRARY),"record_count":records,"transition_count":trans,"deterministic":True,"future_information_allowed":False,"historical_outcomes_used_in_live_selection":False,"recommendation_mutation_enabled":False,"confidence_mutation_enabled":False,"production_effect":"NONE"}

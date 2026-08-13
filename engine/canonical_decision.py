"""APEX 47.0.2 — one canonical decision snapshot contract."""
from __future__ import annotations
import hashlib, json, math
from datetime import datetime, timezone
from typing import Any, Mapping

VERSION="47.0.2"; SCHEMA_VERSION="apex.canonical_decision.v1"

def _num(v, default=None):
    try:
        x=float(v); return x if math.isfinite(x) else default
    except (TypeError,ValueError): return default

def _direction(src: Mapping[str,Any]) -> str:
    values=[src.get("direction"),src.get("bias"),src.get("decision"),src.get("recommendation"),
            (src.get("market_narrative") or {}).get("direction"),
            (src.get("trade_director") or {}).get("direction")]
    text=" ".join(str(v or "").upper() for v in values)
    if any(x in text for x in ("BULL","CALL","LONG")): return "BULLISH"
    if any(x in text for x in ("BEAR","PUT","SHORT")): return "BEARISH"
    return "NEUTRAL"

def _action(src: Mapping[str,Any]) -> str:
    raw=str(src.get("action") or src.get("decision_state") or (src.get("trade_director") or {}).get("action") or "STAND_DOWN").upper()
    if any(x in raw for x in ("ENTER","EXECUTE","BUY","LONG","SHORT")): return "ENTER"
    if "HOLD" in raw: return "HOLD"
    if any(x in raw for x in ("EXIT","CLOSE","FLATTEN")): return "EXIT"
    return "STAND_DOWN"

def build_snapshot(source: Mapping[str,Any] | None, ticker: str="SPX") -> dict[str,Any]:
    s=dict(source or {}); ms=s.get("market_state") or {}; st=s.get("structure") or {}; li=s.get("liquidity_intelligence") or {}
    now=str(s.get("timestamp") or s.get("observed_at") or datetime.now(timezone.utc).isoformat())
    direction=_direction(s); action=_action(s)
    price=_num(ms.get("price") or s.get("spot") or s.get("price") or (s.get("flow") or {}).get("stock_price"))
    confidence=_num(s.get("confidence") or (s.get("market_narrative") or {}).get("confidence") or (s.get("trade_director") or {}).get("confidence"),50.0)
    payload_key=f"{ticker}|{now}|{direction}|{action}|{price}"
    decision_id=hashlib.sha256(payload_key.encode()).hexdigest()[:24]
    features={}
    try:
        from engine.adaptive_learning import extract_features
        features=extract_features(s)
    except Exception: pass
    target=(li.get("race") or {}).get("leading_level") or s.get("target") or st.get("next_resistance" if direction=="BULLISH" else "next_support")
    invalidation=s.get("invalidation") or st.get("support" if direction=="BULLISH" else "resistance")
    session=str(s.get("session") or ms.get("session") or "UNKNOWN").upper()
    learning_eligible=bool(action=="ENTER" and direction in {"BULLISH","BEARISH"} and price is not None and session not in {"CLOSED","MARKET_CLOSED","AFTER_HOURS"})
    return {
      "ok":True,"schema_version":SCHEMA_VERSION,"engine_version":VERSION,"decision_id":decision_id,
      "timestamp":now,"ticker":str(ticker or s.get("ticker") or "SPX").upper(),"session":session,
      "direction":direction,"action":action,"setup_family":str(s.get("setup_family") or s.get("signal_family") or "UNCLASSIFIED"),
      "confidence":round(max(0,min(100,confidence or 50)),2),"entry_reference":price,
      "invalidation":_num(invalidation),"target":_num(target),"feature_vector":features,
      "liquidity_context":li,"order_flow_context":s.get("flow_intelligence_2") or s.get("flow_intelligence") or {},
      "auction_context":s.get("auction_intelligence") or s.get("auction") or {},"gamma_context":s.get("gamma_regime") or {},
      "narrative":s.get("market_narrative") or {},"learning_eligible":learning_eligible,
      "execution_authorized":False,"market_state":{"price":price,"session":session},
    }

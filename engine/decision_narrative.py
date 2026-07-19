"""APEX 18.2.1 — Decision Narrative."""
from __future__ import annotations
import datetime as dt
from typing import Any, Dict, List
VERSION="18.2.1_DECISION_NARRATIVE"

def _num(v, default=0.0):
    try:return float(v)
    except Exception:return default

def build_decision_narrative(*, eligibility:Dict[str,Any], intelligence:Dict[str,Any], portfolio:Dict[str,Any], execution:Dict[str,Any], risk:Dict[str,Any], learning:Dict[str,Any]) -> Dict[str,Any]:
    rec=(intelligence or {}).get("recommendation") or {}
    if not isinstance(rec, dict):
        rec={}
    selected=portfolio.get("selected_positions") or [{}]
    first=selected[0] if isinstance(selected, list) and selected and isinstance(selected[0], dict) else {}
    strategy=rec.get("strategy") or first.get("strategy") or "NO_TRADE"
    blockers=list(eligibility.get("blockers") or [])+list(risk.get("blockers") or [])
    evidence=[]
    evidence.append(f"Premium eligibility is {eligibility.get('decision','UNKNOWN')} at {eligibility.get('score',0)} against threshold {eligibility.get('threshold','unknown')}.")
    if rec: evidence.append(f"{strategy} ranks first with institutional score {rec.get('institutional_score', rec.get('score','unknown'))} and expected value {rec.get('expected_value','unknown')}.")
    if execution.get("recommendation"):
        er=execution["recommendation"]; evidence.append(f"Execution model reports {er.get('status','UNKNOWN')} with adjusted expected value {er.get('execution_adjusted_expected_value','unknown')}.")
    if learning.get("best_pattern"):
        p=learning["best_pattern"]; evidence.append(f"Best learned analogue is {p.get('strategy')} in {p.get('regime')} with {p.get('samples')} samples, {round(_num(p.get('win_rate'))*100,1)}% wins, and average P/L {p.get('average_pnl')}.")
    decision="STAND_DOWN" if blockers or risk.get("decision") in {"BLOCKED","REDUCE"} and not portfolio.get("selected_positions") else ("APPROVE_PREVIEW" if strategy!="NO_TRADE" else "STAND_DOWN")
    headline=(f"{decision}: {strategy}" if strategy!="NO_TRADE" else "STAND DOWN — NO INSTITUTIONAL EDGE")
    return {"version":VERSION,"generated_at":dt.datetime.now(dt.timezone.utc).isoformat(),"decision":decision,"headline":headline,"strategy":strategy,"summary":" ".join(evidence[:3]),"evidence":evidence,"blockers":blockers,"warnings":list(eligibility.get("warnings") or [])+list(risk.get("warnings") or []),"advisory_only":True,"execution_authority":False}

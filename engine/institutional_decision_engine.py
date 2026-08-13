"""APEX 20.0 Institutional Decision Engine.

Read-only evidence fusion across the APEX 19.x intelligence suite. The engine
produces one explainable decision object and never submits, previews, or mutates
broker orders.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List
import math

from .institutional_dealer_positioning_engine import build_dealer_positioning
from .institutional_options_flow_engine import build_options_flow_intelligence
from .institutional_probability_engine import build_probability_engine
from .institutional_market_structure_engine import build_institutional_market_structure
from .institutional_decision_object import build_canonical_institutional_decision

VERSION = "13.0.0_INSTITUTIONAL_DECISION_ENGINE"
SEMANTIC_VERSION = "13.0.0"


def _f(v: Any, d: float = 0.0) -> float:
    try:
        n = float(v)
        return d if math.isnan(n) or math.isinf(n) else n
    except Exception:
        return d


def _clip(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return round(max(lo, min(hi, v)), 1)


def _dir(v: Any) -> str:
    s = str(v or "").upper()
    if any(x in s for x in ("BULL", "CALL", "UP", "RISING", "BUY", "ABOVE")):
        return "BULLISH"
    if any(x in s for x in ("BEAR", "PUT", "DOWN", "FALLING", "SELL", "BELOW")):
        return "BEARISH"
    return "NEUTRAL"


def _strategy(bias: str, regime: str, confidence: float, probability: Dict[str, Any]) -> Dict[str, Any]:
    trend = _f(probability.get("trend_day_probability"), 50)
    if bias == "NEUTRAL":
        name = "IRON_CONDOR_OR_STAND_DOWN" if regime == "BALANCE" else "STAND_DOWN"
        rationale = "Directional evidence is not sufficiently aligned."
    elif regime == "EXPANSION" and trend >= 60:
        name = "DIRECTIONAL_DEBIT_SPREAD"
        rationale = "Directional evidence and expansion probability favor defined-risk participation."
    elif regime == "MEAN_REVERSION":
        name = "DEFINED_RISK_CREDIT_SPREAD"
        rationale = "Positive-gamma or balance conditions favor premium-defined mean reversion."
    else:
        name = "PULLBACK_DIRECTIONAL"
        rationale = "Wait for price confirmation at a governed structure level rather than chase."
    return {"name": name, "bias": bias, "confidence": confidence, "rationale": rationale,
            "advisory_only": True, "requires_option_chain_validation": True}


def build_institutional_decision(last: Dict[str, Any], history: Any = None) -> Dict[str, Any]:
    """Legacy APEX 20.0 compatibility adapter over the canonical v3 decision.

    Primitive components remain available for diagnostics, but this legacy surface
    no longer independently synthesizes authoritative consensus, conviction, thesis,
    or actionability.
    """
    last = last if isinstance(last, dict) else {}
    dealer = build_dealer_positioning(last)
    flow = build_options_flow_intelligence(last)
    structure = build_institutional_market_structure(last)
    probability = build_probability_engine(last, dealer, flow, structure)
    learning = build_adaptive_learning_v2(last, history)

    adapted = dict(last)
    adapted["dealer_positioning"] = dealer
    adapted["flow_intelligence_2"] = flow
    adapted["institutional_market_structure"] = structure
    # Preserve an already-normalized institutional intelligence object when the
    # caller supplied it; do not manufacture one from the legacy components.
    canonical = build_canonical_institutional_decision(
        adapted, session_state=(last.get("session") or (last.get("market_state") or {}).get("session_state"))
    )
    consensus = canonical.get("consensus") or {}
    conviction = canonical.get("conviction") or {}
    bias = str(canonical.get("direction") or "NEUTRAL").upper()
    confidence = _clip(_f(conviction.get("raw_conviction") or conviction.get("score"), 0.0))

    gamma_regime = dealer.get("gamma_regime")
    day_class = (structure.get("day_type_probability") or {}).get("classification")
    regime = "EXPANSION" if gamma_regime == "NEGATIVE_GAMMA" or day_class == "TREND_FAVORED" else "MEAN_REVERSION" if gamma_regime == "POSITIVE_GAMMA" else "BALANCE"
    fresh = not (last.get("data_fresh") is False or (last.get("market_state") or {}).get("data_fresh") is False or "STALE_DATA" in probability.get("warnings", []))
    blockers = list(conviction.get("blocking_conditions") or [])
    if not fresh and "STALE_DATA" not in blockers: blockers.append("STALE_DATA")
    if canonical.get("fail_closed") and "CANONICAL_FAIL_CLOSED" not in blockers: blockers.append("CANONICAL_FAIL_CLOSED")
    execution_eligible = bool(canonical.get("actionable") and fresh and not blockers)
    decision = "TRADE_CANDIDATE" if execution_eligible else "WATCH" if fresh and bias in {"BULLISH", "BEARISH"} else "STAND_DOWN"

    # Legacy evidence rows remain for response compatibility only. They are not
    # used to recompute the canonical consensus.
    evidence = [
        {"source":"dealer","available":bool(dealer.get("available", False)),"direction":_dir(dealer.get("bias")),"confidence":_clip(abs(_f(dealer.get("pressure_score")))),"weight":0.22,"contribution":None},
        {"source":"flow","available":bool(flow.get("available", False)),"direction":_dir(flow.get("bias")),"confidence":_clip(abs(_f(flow.get("net_flow_score")))),"weight":0.22,"contribution":None},
        {"source":"market_structure","available":structure.get("state") != "DEGRADED","direction":_dir(structure.get("direction")),"confidence":70.0 if structure.get("state")=="READY" else 45.0,"weight":0.24,"contribution":None},
        {"source":"probability","available":probability.get("state") != "DEGRADED","direction":"BULLISH" if _f((probability.get("directional") or {}).get("bullish"),50)>=55 else "BEARISH" if _f((probability.get("directional") or {}).get("bearish"),50)>=55 else "NEUTRAL","confidence":abs(_f((probability.get("directional") or {}).get("bullish"),50)-50)*2,"weight":0.24,"contribution":None},
        {"source":"adaptive_learning","available":learning.get("sample_size",0)>0,"direction":"NEUTRAL","confidence":min(100,_f(learning.get("sample_size"))/30*100),"weight":0.08,"contribution":None},
    ]
    conflicts = list(consensus.get("contradicting_engines") or consensus.get("dissenters") or [])
    coverage = (_f(consensus.get("evidence_coverage"), 0.0) / 100.0)
    agreement = _f(consensus.get("effective_consensus") or consensus.get("score"), 0.0)
    bull_prob = _f((probability.get("directional") or {}).get("bullish"), 50)
    scenarios = [
        {"name":"BULL_CASE","probability":bull_prob,"confirmation":"Acceptance above governed resistance or value with persistent bullish flow."},
        {"name":"BEAR_CASE","probability":round(100-bull_prob,1),"confirmation":"Acceptance below governed support or value with persistent bearish flow."},
        {"name":"BALANCE_CASE","probability":_clip(100-abs(bull_prob-50)*2),"confirmation":"Repeated rejection at both sides of value and declining directional persistence."},
    ]
    headline = f"{bias} {regime.replace('_',' ')} — raw conviction {confidence:.0f}/100"
    narrative = canonical.get("narrative", {}).get("executive_summary") or "Canonical institutional decision unavailable."
    return {
        "ok": True, "version": VERSION, "semantic_version": SEMANTIC_VERSION,
        "evaluated_at": canonical.get("timestamp") or datetime.now(timezone.utc).isoformat(), "ticker": str(last.get("ticker") or "SPX"),
        "decision": decision, "bias": bias, "regime": regime, "confidence": confidence,
        "headline": headline, "narrative": narrative, "execution_eligible": execution_eligible,
        "blocking_reasons": blockers, "conflicting_sources": conflicts, "evidence_coverage": round(coverage,2),
        "agreement_score": round(agreement,1), "evidence": evidence, "scenarios": scenarios,
        "strategy": _strategy(bias, regime, confidence, probability),
        "levels": structure.get("institutional_levels") or structure.get("levels") or {},
        "components": {"dealer": dealer, "flow": flow, "market_structure": structure, "probability": probability, "adaptive_learning": learning},
        "canonical_decision": canonical,
        "compatibility_adapter": True,
        "authoritative_decision_source": "engine.institutional_decision_object",
        "guardrails": {"read_only": True, "broker_mutation": False, "automatic_execution": False,
                       "human_confirmation_required": True, "existing_kill_switch_authoritative": True,
                       "does_not_change_execution_permissions": True, "independent_consensus_disabled": True}
    }


# ── Route registration (absorbed from institutional_decision_engine_routes.py,
#    Sprint 2). Read-only API for the APEX 20.0 Institutional Decision Engine.
from flask import jsonify  # noqa: E402


def register_institutional_decision_engine_routes(app, last_result_provider):
    def cur():
        value = last_result_provider() if callable(last_result_provider) else {}
        return value if isinstance(value, dict) else {}
    @app.get('/api/institutional-decision/status')
    def institutional_decision_status():
        x=build_institutional_decision(cur())
        return jsonify({k:x[k] for k in ('ok','version','semantic_version','evaluated_at','ticker','decision','bias','regime','confidence','headline','execution_eligible','blocking_reasons','evidence_coverage','agreement_score','guardrails')})
    @app.get('/api/institutional-decision/diagnostics')
    def institutional_decision_diagnostics(): return jsonify(build_institutional_decision(cur()))
    @app.get('/api/institutional-decision/scenarios')
    def institutional_decision_scenarios():
        x=build_institutional_decision(cur()); return jsonify({'ok':True,'version':x['version'],'scenarios':x['scenarios'],'bias':x['bias'],'confidence':x['confidence']})
    @app.get('/api/institutional-decision/evidence')
    def institutional_decision_evidence():
        x=build_institutional_decision(cur()); return jsonify({'ok':True,'version':x['version'],'evidence':x['evidence'],'conflicting_sources':x['conflicting_sources'],'agreement_score':x['agreement_score']})
    @app.get('/api/institutional-decision/strategy')
    def institutional_decision_strategy():
        x=build_institutional_decision(cur()); return jsonify({'ok':True,'version':x['version'],'strategy':x['strategy'],'execution_eligible':x['execution_eligible'],'blocking_reasons':x['blocking_reasons'],'guardrails':x['guardrails']})


# ── Adaptive Learning Engine v2 (absorbed from adaptive_learning_engine_v2.py,
#    Sprint 4). Bounded, audit-friendly calibration; NaN/inf-guarded numerics
#    preserved verbatim under _f_finite. Payload version string unchanged.
ALE2_VERSION = '12.5.0_ADAPTIVE_LEARNING_ENGINE_V2'

def _f_finite(v,d=0.0):
    try:
        x=float(v); return d if math.isnan(x) or math.isinf(x) else x
    except Exception:return d
def build_adaptive_learning_v2(last:Dict[str,Any], history=None)->Dict[str,Any]:
    rows=history if isinstance(history,list) else last.get('recommendation_history') or last.get('graded_recommendations') or []
    rows=[x for x in rows if isinstance(x,dict) and str(x.get('outcome','')).upper() not in ('NOT_EXECUTABLE','PENDING','')]
    buckets={}; wins=0
    for r in rows:
        won=str(r.get('outcome') or r.get('result')).upper() in ('WIN','WON','SUCCESS','PROFIT'); wins+=int(won)
        setup=str(r.get('setup') or r.get('strategy_family') or 'UNKNOWN'); regime=str(r.get('regime') or 'UNKNOWN'); hour=str(r.get('hour') or r.get('time_bucket') or 'UNKNOWN')
        for kind,key in (('setup',setup),('regime',regime),('time',hour)):
            b=buckets.setdefault(kind,{}).setdefault(key,{'samples':0,'wins':0}); b['samples']+=1;b['wins']+=int(won)
    insights=[]
    for kind,vals in buckets.items():
        for key,b in vals.items():
            rate=b['wins']/b['samples']*100
            if b['samples']>=5: insights.append({'dimension':kind,'value':key,'samples':b['samples'],'win_rate':round(rate,1),'confidence':'HIGH' if b['samples']>=30 else 'MEDIUM'})
    insights.sort(key=lambda x:(x['win_rate'],x['samples']),reverse=True)
    n=len(rows); raw=round(wins/n*100,1) if n else None
    # Bounded suggestions only; no live self-modification.
    suggestions=[]
    for x in insights[:8]:
        delta=max(-10,min(10,(x['win_rate']-50)*.2))
        suggestions.append({**x,'suggested_weight_delta':round(delta,2),'applied':False})
    readiness='READY_FOR_REVIEW' if n>=30 else 'COLLECTING_DATA'
    return {'ok':True,'version':ALE2_VERSION,'evaluated_at':datetime.now(timezone.utc).isoformat(),'state':'READY' if n else 'DEGRADED','sample_size':n,'win_rate':raw,'learning_readiness':readiness,'best_patterns':insights[:10],'weight_suggestions':suggestions,'calibration':{'automatic_application':False,'max_suggested_delta_pct':10,'not_executable_excluded':True,'minimum_samples':30},'guardrails':{'read_only':True,'broker_mutation':False,'automatic_weight_changes':False,'human_approval_required':True,'lookahead_protection_required':True}}


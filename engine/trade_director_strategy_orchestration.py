"""APEX Trade Director Phase 14 — Strategy Orchestration & Opportunity Ranking.

Pure advisory analytics. The engine ranks defined-risk SPX strategy families from
already-built Trade Director intelligence. It never requests market data, opens a
broker connection, constructs executable option symbols, or transmits orders.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Iterable, List, Mapping, Optional


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _nested(payload: Mapping[str, Any], *paths: str, default: Any = None) -> Any:
    for path in paths:
        cur: Any = payload
        ok = True
        for part in path.split('.'):
            if not isinstance(cur, Mapping) or part not in cur:
                ok = False
                break
            cur = cur[part]
        if ok and cur is not None:
            return cur
    return default


def _direction(context: Mapping[str, Any]) -> str:
    values = [
        _nested(context, 'cross_asset_intelligence.cross_asset_bias'),
        _nested(context, 'market_memory.predictive_session_planner.directional_bias'),
        _nested(context, 'institutional_analysis.expected_path'),
        context.get('side'),
        _nested(context, 'flow_snapshot.bias'),
    ]
    bull = bear = 0
    for value in values:
        text = str(value or '').upper()
        if any(t in text for t in ('BULL', 'CALL', 'UP', 'HIGHER', 'RISK_ON')):
            bull += 1
        elif any(t in text for t in ('BEAR', 'PUT', 'DOWN', 'LOWER', 'RISK_OFF')):
            bear += 1
    return 'BULLISH' if bull > bear else 'BEARISH' if bear > bull else 'NEUTRAL'


def _regime(context: Mapping[str, Any]) -> str:
    return str(
        _nested(context, 'cross_asset_intelligence.regime', default=None)
        or _nested(context, 'management_policy.regime', default=None)
        or _nested(context, 'market_memory.predictive_session_planner.expected_session_type', default=None)
        or 'DATA_LIMITED'
    ).upper()


def _session_mode(context: Mapping[str, Any]) -> str:
    return str(_nested(context, 'session_intelligence.session.mode', default='OBSERVATION')).upper()


def _base_inputs(context: Mapping[str, Any]) -> Dict[str, Any]:
    cross = dict(context.get('cross_asset_intelligence') or {})
    health = _f(_nested(context, 'health_engine.score', 'trade_health.score', default=50), 50)
    confidence = _f(context.get('confidence'), 50)
    cross_conf = _f(cross.get('confidence'), 0)
    cross_score = _f(cross.get('spx_confirmation_score'), 50)
    coverage = _f(cross.get('coverage_pct'), 0)
    planner_conf = _f(_nested(context, 'market_memory.predictive_session_planner.confidence', default=0))
    risk_remaining = _f(_nested(context, 'session_intelligence.risk_budget.remaining_risk', default=0))
    risk_max = _f(_nested(context, 'session_intelligence.risk_budget.maximum_daily_risk', default=0))
    risk_capacity = (risk_remaining / risk_max * 100.0) if risk_max > 0 else 50.0
    high_divs = sum(1 for row in cross.get('divergences') or [] if str(row.get('severity')).upper() == 'HIGH')
    return {
        'direction': _direction(context), 'regime': _regime(context), 'session_mode': _session_mode(context),
        'health': health, 'confidence': confidence, 'cross_confidence': cross_conf,
        'cross_score': cross_score, 'coverage': coverage, 'planner_confidence': planner_conf,
        'risk_capacity': _clamp(risk_capacity), 'high_divergences': high_divs,
    }


def _candidate(name: str, family: str, direction: str, defined_risk: bool = True) -> Dict[str, Any]:
    return {
        'strategy': name, 'family': family, 'direction': direction,
        'defined_risk': defined_risk, 'score': 0.0, 'status': 'REVIEW',
        'reasons': [], 'risks': [], 'structure_guidance': {},
    }


def _rank_candidates(inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
    direction, regime = inputs['direction'], inputs['regime']
    candidates = [
        _candidate('LONG_CALL', 'DIRECTIONAL_PREMIUM', 'BULLISH'),
        _candidate('CALL_DEBIT_SPREAD', 'DIRECTIONAL_DEFINED_RISK', 'BULLISH'),
        _candidate('BULL_PUT_CREDIT_SPREAD', 'PREMIUM_DEFINED_RISK', 'BULLISH'),
        _candidate('LONG_PUT', 'DIRECTIONAL_PREMIUM', 'BEARISH'),
        _candidate('PUT_DEBIT_SPREAD', 'DIRECTIONAL_DEFINED_RISK', 'BEARISH'),
        _candidate('BEAR_CALL_CREDIT_SPREAD', 'PREMIUM_DEFINED_RISK', 'BEARISH'),
        _candidate('IRON_CONDOR', 'NEUTRAL_PREMIUM', 'NEUTRAL'),
        _candidate('STAND_DOWN', 'CAPITAL_PRESERVATION', 'NEUTRAL'),
    ]
    directional_strength = abs(inputs['cross_score'] - 50) * 2
    evidence = (inputs['confidence'] * .22 + inputs['cross_confidence'] * .22 + inputs['planner_confidence'] * .16 + inputs['health'] * .20 + inputs['coverage'] * .20)
    trend_regime = any(t in regime for t in ('TREND', 'EXPANSION', 'TECH_LED', 'RISK_ON', 'RISK_OFF', 'PRESSURE'))
    balanced_regime = any(t in regime for t in ('BALANCED', 'ROTATION', 'MIXED', 'CONFLICT', 'COMPRESSION'))
    for c in candidates:
        score = 35.0
        if inputs['session_mode'] == 'STOP_TRADING':
            if c['strategy'] == 'STAND_DOWN':
                c['score'] = 100.0
                c['status'] = 'PREFERRED'
                c['reasons'].append('Session risk governor is in STOP TRADING mode')
                c['risks'].append('Do not reopen risk until the session governor resets')
            else:
                c['score'] = 0.0
                c['status'] = 'AVOID'
                c['risks'].append('Blocked by the session STOP TRADING governor')
            continue
        if c['strategy'] == 'STAND_DOWN':
            score = 28 + max(0, 58 - evidence) + inputs['high_divergences'] * 12
            if inputs['session_mode'] in ('STOP_TRADING', 'LOCK_PROFIT'):
                score += 45
                c['reasons'].append(f"Session mode is {inputs['session_mode'].replace('_', ' ')}")
            if inputs['coverage'] < 35:
                score += 20
                c['reasons'].append('Cross-asset coverage is insufficient')
            if inputs['direction'] == 'NEUTRAL':
                score += 8
            c['risks'].append('Standing down can miss a later valid setup; reassess when evidence changes')
        elif c['direction'] == direction and direction != 'NEUTRAL':
            score += 22 + directional_strength * .22 + evidence * .22
            c['reasons'].append(f"Aligned with the {direction.lower()} composite bias")
        elif c['direction'] == 'NEUTRAL' and direction == 'NEUTRAL':
            score += 24 + evidence * .12
            c['reasons'].append('Directional evidence is balanced')
        else:
            score -= 20
            c['risks'].append('Conflicts with the current composite direction')

        if c['family'] == 'DIRECTIONAL_PREMIUM':
            score += 12 if trend_regime else -5
            score += 6 if inputs['health'] >= 70 else -6
            c['structure_guidance'] = {'entry_style': 'CONFIRMATION_OR_PULLBACK', 'exit_priority': 'FAST_THESIS_INVALIDATION', 'theta_exposure': 'HIGH'}
            c['risks'].append('Long premium requires prompt directional follow-through')
        elif c['family'] == 'DIRECTIONAL_DEFINED_RISK':
            score += 15 if trend_regime else 5
            score += 7 if 50 <= evidence < 80 else 2
            c['structure_guidance'] = {'entry_style': 'CONFIRMED_DIRECTION', 'width_policy': 'RISK_BUDGET_CONSTRAINED', 'theta_exposure': 'MODERATE'}
            c['reasons'].append('Defined risk reduces premium and volatility exposure')
        elif c['family'] == 'PREMIUM_DEFINED_RISK':
            score += 10 if balanced_regime else 2
            score += 5 if inputs['health'] >= 55 else -8
            c['structure_guidance'] = {'entry_style': 'SELL_BEYOND_INVALIDATION', 'width_policy': 'DEFINED_RISK_ONLY', 'profit_policy': 'EARLY_CAPTURE'}
            c['risks'].append('Short premium must not be used against an accelerating trend')
        elif c['family'] == 'NEUTRAL_PREMIUM':
            score += 22 if balanced_regime and direction == 'NEUTRAL' else -18
            score -= inputs['high_divergences'] * 8
            c['structure_guidance'] = {'entry_style': 'BALANCED_AUCTION_ONLY', 'short_strikes': 'OUTSIDE_EXPECTED_RANGE', 'risk_policy': 'DEFINED_WINGS_REQUIRED'}
            c['risks'].append('Avoid when price discovery or volatility expansion is active')

        if inputs['session_mode'] == 'DEFENSE':
            score += 5 if c['defined_risk'] and c['family'] != 'DIRECTIONAL_PREMIUM' else -10
        elif inputs['session_mode'] == 'ATTACK' and c['direction'] == direction:
            score += 5
        if inputs['risk_capacity'] < 25 and c['strategy'] != 'STAND_DOWN':
            score -= 22
            c['risks'].append('Remaining session risk capacity is low')
        if inputs['high_divergences'] and c['strategy'] != 'STAND_DOWN':
            score -= inputs['high_divergences'] * 8
            c['risks'].append('High-severity cross-asset divergence reduces conviction')
        c['score'] = round(_clamp(score), 1)
        c['status'] = 'PREFERRED' if c['score'] >= 75 else 'ELIGIBLE' if c['score'] >= 58 else 'REVIEW' if c['score'] >= 42 else 'AVOID'
    return sorted(candidates, key=lambda row: row['score'], reverse=True)


def build_strategy_orchestration(context: Optional[Dict[str, Any]], historical_trades: Iterable[Dict[str, Any]] = ()) -> Dict[str, Any]:
    context = dict(context or {})
    inputs = _base_inputs(context)
    ranked = _rank_candidates(inputs)
    winner = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None
    eligible = [r for r in ranked if r['status'] in ('PREFERRED', 'ELIGIBLE') and r['strategy'] != 'STAND_DOWN']
    gate = 'STAND_DOWN' if winner['strategy'] == 'STAND_DOWN' else 'STRATEGY_SELECTED' if winner['score'] >= 68 else 'WAIT_FOR_CONFIRMATION'
    history = list(historical_trades or [])
    family_stats: Dict[str, Dict[str, Any]] = {}
    for row in history:
        family = str(row.get('strategy') or row.get('trade_type') or 'UNKNOWN').upper()
        pnl = _f(row.get('realized_pnl', row.get('pnl', 0)))
        bucket = family_stats.setdefault(family, {'samples': 0, 'wins': 0, 'total_pnl': 0.0})
        bucket['samples'] += 1; bucket['wins'] += int(pnl > 0); bucket['total_pnl'] += pnl
    learned = []
    for family, stats in family_stats.items():
        learned.append({'strategy': family, 'samples': stats['samples'], 'win_rate': round(stats['wins'] / stats['samples'] * 100, 1), 'total_pnl': round(stats['total_pnl'], 2)})
    return {
        'version': 'PHASE_14', 'as_of': _now(), 'mode': 'ADVISORY_ONLY',
        'decision_gate': gate, 'selected_strategy': winner,
        'runner_up': runner_up, 'opportunity_queue': ranked,
        'eligible_strategy_count': len(eligible), 'market_inputs': inputs,
        'historical_strategy_memory': {'rows': sorted(learned, key=lambda x: (x['samples'], x['win_rate']), reverse=True)[:8], 'sample_count': len(history), 'status': 'LEARNING' if len(history) < 30 else 'ACTIVE'},
        'execution_contract': {
            'executable': False, 'option_contract_selected': False, 'strikes_selected': False,
            'broker_preview_created': False,
            'note': 'Phase 14 selects a strategy family only. Phase 9 and Phase 10 remain authoritative for risk, confirmation, and execution.'
        },
        'safety_note': 'No provider or broker requests were made. Rankings use cached APEX intelligence and defined-risk policy rules.',
    }

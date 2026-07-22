"""APEX Trade Director Phase 15 — Options Intelligence Engine.

Deterministic, advisory contract intelligence. It ranks normalized contracts already
present in APEX memory or explicitly supplied by the caller. It never fetches an
option chain, contacts a broker, previews an order, or fabricates a contract.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


def _f(v: Any, default: float = 0.0) -> float:
    try:
        n = float(v)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _text(v: Any) -> str:
    return str(v or "").strip()


def _nested(root: Mapping[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = root
    for part in path.split('.'):
        if not isinstance(cur, Mapping) or part not in cur:
            return default
        cur = cur[part]
    return default if cur is None else cur


def _strategy_profile(strategy: str) -> Dict[str, Any]:
    s = strategy.upper()
    profiles = {
        'LONG_CALL': ('CALL', 0.42, 0.62, '0DTE_OR_1DTE', 'SINGLE_LEG'),
        'LONG_PUT': ('PUT', 0.42, 0.62, '0DTE_OR_1DTE', 'SINGLE_LEG'),
        'CALL_DEBIT_SPREAD': ('CALL', 0.48, 0.65, '0DTE_OR_1DTE', 'DEBIT_SPREAD'),
        'PUT_DEBIT_SPREAD': ('PUT', 0.48, 0.65, '0DTE_OR_1DTE', 'DEBIT_SPREAD'),
        'BULL_PUT_CREDIT_SPREAD': ('PUT', 0.12, 0.30, '0DTE_OR_1DTE', 'CREDIT_SPREAD'),
        'BEAR_CALL_CREDIT_SPREAD': ('CALL', 0.12, 0.30, '0DTE_OR_1DTE', 'CREDIT_SPREAD'),
        'IRON_CONDOR': ('BOTH', 0.10, 0.25, '0DTE_OR_1DTE', 'IRON_CONDOR'),
    }
    side, dlo, dhi, exp, structure = profiles.get(s, ('BOTH', 0.30, 0.55, 'NEXT_LIQUID_EXPIRATION', 'GUIDANCE_ONLY'))
    return {'side': side, 'delta_low': dlo, 'delta_high': dhi, 'expiration_policy': exp, 'structure': structure}


def _normalize_contract(row: Mapping[str, Any]) -> Dict[str, Any]:
    bid = _f(row.get('bid'), -1)
    ask = _f(row.get('ask'), -1)
    mid = _f(row.get('mid'), (bid + ask) / 2 if bid >= 0 and ask >= 0 else 0)
    spread = ask - bid if bid >= 0 and ask >= bid else None
    spread_pct = (spread / mid * 100.0) if spread is not None and mid > 0 else None
    side = _text(row.get('side') or row.get('option_type') or row.get('type')).upper()
    if side in ('C', 'CALLS'): side = 'CALL'
    if side in ('P', 'PUTS'): side = 'PUT'
    delta = abs(_f(row.get('delta'), 0))
    return {
        'symbol': row.get('osi_key') or row.get('symbol') or row.get('contract_symbol'),
        'side': side, 'strike': _f(row.get('strike'), 0),
        'expiration': row.get('expiration') or row.get('expiration_date') or row.get('expiry'),
        'bid': None if bid < 0 else bid, 'ask': None if ask < 0 else ask,
        'mid': mid or None, 'spread_pct': None if spread_pct is None else round(spread_pct, 2),
        'delta': delta or None, 'gamma': row.get('gamma'), 'theta': row.get('theta'),
        'vega': row.get('vega'), 'iv': row.get('iv') or row.get('implied_volatility'),
        'volume': int(_f(row.get('volume'), 0)),
        'open_interest': int(_f(row.get('open_interest') or row.get('oi'), 0)),
        'source': row.get('source'), 'raw': dict(row),
    }


def _contract_score(c: Dict[str, Any], profile: Dict[str, Any], spot: float, expected_move: float) -> Dict[str, Any]:
    reasons: List[str] = []
    blockers: List[str] = []
    score = 0.0
    side = profile['side']
    if side != 'BOTH' and c['side'] != side:
        blockers.append(f"Contract side {c['side'] or 'UNKNOWN'} conflicts with required {side}")
    delta = c['delta']
    if delta is None:
        score += 6
        reasons.append('Delta unavailable; contract cannot receive full Greeks credit')
    else:
        lo, hi = profile['delta_low'], profile['delta_high']
        center = (lo + hi) / 2
        distance = abs(delta - center)
        score += max(0, 30 - distance * 120)
        if lo <= delta <= hi:
            reasons.append(f"Delta {delta:.2f} is inside the preferred range")
        else:
            reasons.append(f"Delta {delta:.2f} is outside the preferred {lo:.2f}-{hi:.2f} range")
    sp = c['spread_pct']
    if sp is None:
        blockers.append('No valid two-sided quote')
    elif sp <= 5:
        score += 25; reasons.append('Tight bid/ask spread')
    elif sp <= 10:
        score += 17; reasons.append('Acceptable bid/ask spread')
    elif sp <= 18:
        score += 7; reasons.append('Wide bid/ask spread')
    else:
        blockers.append('Bid/ask spread exceeds 18%')
    vol, oi = c['volume'], c['open_interest']
    score += min(12, math.log10(max(1, vol)) * 4)
    score += min(12, math.log10(max(1, oi)) * 4)
    if vol >= 100: reasons.append('Meaningful same-day volume')
    if oi >= 500: reasons.append('Strong open interest')
    if vol == 0 and oi == 0: blockers.append('No volume or open-interest evidence')
    if spot > 0 and c['strike'] > 0 and expected_move > 0:
        distance = abs(c['strike'] - spot)
        ratio = distance / expected_move
        if ratio <= .35: score += 14; em = 'INSIDE_CORE_EXPECTED_MOVE'
        elif ratio <= .8: score += 10; em = 'INSIDE_EXPECTED_MOVE'
        elif ratio <= 1.15: score += 5; em = 'NEAR_EXPECTED_MOVE_EDGE'
        else: score -= 8; em = 'OUTSIDE_EXPECTED_MOVE'
    else:
        ratio, em = None, 'UNAVAILABLE'
    if c['gamma'] is not None: score += 3
    if c['theta'] is not None: score += 2
    if c['vega'] is not None: score += 2
    if c['iv'] is not None: score += 2
    if not c['symbol'] or not c['expiration'] or not c['strike']:
        blockers.append('Contract identity is incomplete')
    score = _clamp(score - len(blockers) * 18)
    return {
        **{k: v for k, v in c.items() if k != 'raw'},
        'score': round(score, 1), 'status': 'ELIGIBLE' if score >= 62 and not blockers else 'REVIEW' if score >= 42 else 'REJECTED',
        'expected_move_position': em, 'expected_move_ratio': None if ratio is None else round(ratio, 3),
        'reasons': reasons[:6], 'blockers': blockers,
    }


def _guidance(strategy: str, profile: Dict[str, Any], context: Mapping[str, Any]) -> Dict[str, Any]:
    confidence = _f(_nested(context, 'strategy_orchestration.selected_strategy.score', 0))
    regime = _text(_nested(context, 'strategy_orchestration.market_inputs.regime', 'DATA_LIMITED')).upper()
    exp = '0DTE' if confidence >= 72 and any(x in regime for x in ('TREND', 'EXPANSION', 'RISK_ON', 'RISK_OFF')) else '1DTE_OR_NEAREST_LIQUID'
    if strategy in ('IRON_CONDOR', 'BULL_PUT_CREDIT_SPREAD', 'BEAR_CALL_CREDIT_SPREAD'):
        exp = '0DTE_ONLY_WHEN_BALANCED_ELSE_1DTE'
    return {
        'strategy': strategy, 'required_side': profile['side'], 'structure': profile['structure'],
        'preferred_abs_delta': {'minimum': profile['delta_low'], 'maximum': profile['delta_high']},
        'expiration_guidance': exp,
        'liquidity_requirements': {'two_sided_quote': True, 'preferred_spread_pct_max': 10, 'hard_spread_pct_max': 18, 'volume_or_open_interest_required': True},
        'strike_guidance': 'ATM_TO_SLIGHTLY_OTM' if profile['delta_low'] >= .35 else 'SHORT_STRIKE_BEYOND_THESIS_INVALIDATION',
        'risk_guidance': 'Use Phase 9 risk budget and Phase 10 confirmation; Phase 15 does not size or transmit orders.',
    }


def build_options_intelligence(context: Optional[Dict[str, Any]], contracts: Iterable[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    context = dict(context or {})
    selected = dict(_nested(context, 'strategy_orchestration.selected_strategy', {}) or {})
    strategy = _text(selected.get('strategy') or 'STAND_DOWN').upper()
    profile = _strategy_profile(strategy)
    spot = _f(context.get('current_price') or _nested(context, 'position.current_price', 0) or _nested(context, 'market_snapshot.spx', 0))
    expected_move = _f(_nested(context, 'market_memory.current_snapshot.expected_move', 0) or _nested(context, 'institutional_analysis.expected_move', 0))
    rows = [_normalize_contract(r) for r in contracts if isinstance(r, Mapping)]
    ranked = sorted((_contract_score(r, profile, spot, expected_move) for r in rows), key=lambda x: x['score'], reverse=True)
    eligible = [r for r in ranked if r['status'] == 'ELIGIBLE']
    best = eligible[0] if eligible else None
    if strategy == 'STAND_DOWN':
        gate, reason = 'STAND_DOWN', 'Phase 14 selected capital preservation.'
    elif not rows:
        gate, reason = 'CHAIN_REQUIRED', 'No cached normalized option chain was available. Contract characteristics are provided without fabricating a symbol, strike, price, or Greeks.'
    elif best is None:
        gate, reason = 'NO_ELIGIBLE_CONTRACT', 'The available chain contained no contract that passed identity, quote, liquidity, and compatibility checks.'
    else:
        gate, reason = 'CONTRACT_CANDIDATE_SELECTED', 'A contract candidate passed Phase 15 advisory checks; Phase 9 and Phase 10 remain authoritative.'
    return {
        'version': 'PHASE_15', 'as_of': _now(), 'mode': 'ADVISORY_ONLY',
        'decision_gate': gate, 'reason': reason, 'strategy': strategy,
        'contract_guidance': _guidance(strategy, profile, context),
        'chain_status': {'available': bool(rows), 'contract_count': len(rows), 'eligible_count': len(eligible), 'spot': spot or None, 'expected_move_points': expected_move or None},
        'best_contract': best, 'alternatives': eligible[1:3], 'ranked_contracts': ranked[:20],
        'greeks_intelligence': {
            'delta': 'Primary directional exposure; target range is strategy-specific.',
            'gamma': 'Higher gamma improves short-horizon responsiveness but increases instability.',
            'theta': 'Long-premium decay must be offset by prompt movement; short premium carries tail risk.',
            'vega': 'Higher vega increases sensitivity to implied-volatility changes.'
        },
        'execution_contract': {'executable': False, 'order_intent_created': False, 'broker_called': False, 'risk_gate_bypassed': False},
        'safety_note': 'Phase 15 ranks only supplied or cached normalized contracts. It performs no provider request, broker request, preview, confirmation, or order transmission.'
    }

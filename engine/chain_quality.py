"""APEX option-chain quality gate.

Scores only observable chain integrity. Missing dimensions are reported as
unmeasurable and excluded from the numeric score; score confidence records how
much of the intended assessment was actually measurable.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional

CHAIN_QUALITY_VERSION = "1.2.0"


def _f(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        out = float(value)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def evaluate_chain_quality(
    contracts: Iterable[Dict[str, Any]],
    *,
    max_quote_age_seconds: float = 15.0,
    max_spread_pct: float = 15.0,
    min_open_interest: int = 1,
    min_volume: int = 1,
) -> Dict[str, Any]:
    rows = [dict(c) for c in (contracts or [])]
    total = len(rows)
    if total == 0:
        return {
            "available": False, "version": CHAIN_QUALITY_VERSION, "score": 0.0,
            "score_confidence_pct": 0.0, "assessment_confidence": "NONE",
            "grade": "UNAVAILABLE", "gate_passed": False,
            "valid_contract_count": 0, "total_contract_count": 0,
            "fresh_quote_pct": None,
            "freshness_unavailable_reason": "No normalized option contracts were available.",
            "warnings": ["No normalized option contracts were available."],
        }

    usable: List[Dict[str, Any]] = []
    crossed = locked = stale = wide = missing_quote = 0
    timestamped = depth_covered = greek_covered = 0

    for row in rows:
        bid, ask = _f(row.get("bid")), _f(row.get("ask"))
        age, spread = _f(row.get("quote_age_seconds")), _f(row.get("spread_pct"))
        volume, oi = _f(row.get("volume")) or 0.0, _f(row.get("open_interest")) or 0.0
        if bid is None or ask is None:
            missing_quote += 1
            continue
        if ask < bid:
            crossed += 1
            continue
        if ask == bid:
            locked += 1
        if age is not None:
            timestamped += 1
            if age > max_quote_age_seconds:
                stale += 1
        if spread is None or spread > max_spread_pct:
            wide += 1
        if volume >= min_volume or oi >= min_open_interest:
            depth_covered += 1
        if any(_f(row.get(k)) is not None for k in ("delta", "gamma", "theta", "vega", "iv")):
            greek_covered += 1
        usable.append(row)

    shape_violations = 0
    ordered = sorted(usable, key=lambda r: (_f(r.get("strike")) or 0.0))
    # Shape is tested against EXECUTABLE prices, not mids. Wide, asymmetric 0DTE
    # quotes routinely invert the mids without any executable arbitrage existing
    # — the exact false positive a mid-based test produces. A monotonicity
    # violation is only real if you could actually put it on for a credit:
    #   calls: ask(low K) < bid(high K)  -> buy low / sell high, collect a credit
    #   puts:  ask(high K) < bid(low K)  -> buy high / sell low, collect a credit
    # Everything short of that is spread noise, not a broken chain.
    convexity_violations = 0
    for left, right in zip(ordered, ordered[1:]):
        lb, la = _f(left.get("bid")), _f(left.get("ask"))
        rb, ra = _f(right.get("bid")), _f(right.get("ask"))
        if None in (lb, la, rb, ra):
            continue
        side = str(left.get("side") or "").upper()
        if side == "CALL" and la < rb:          # ask(lower strike) < bid(higher strike)
            shape_violations += 1
        elif side == "PUT" and ra < lb:         # ask(higher strike) < bid(lower strike)
            shape_violations += 1

    # Convexity (butterfly no-arbitrage): a call/put value curve must be convex in
    # strike, so the cheapest executable body cannot fall below the two wings by
    # more than the executable cost of the fly. Tested only on equal strike spacing,
    # and only when a fly could actually be assembled for a credit — same
    # executable-price discipline as the monotonicity test above.
    # A long butterfly (buy 1 lower wing, buy 1 upper wing, sell 2 bodies) can
    # never be entered for a credit on a convex curve — that would be free money.
    # Executable worst case: pay ask on both wings, receive bid on the two bodies.
    # Violation iff 2*body_bid > wing_ask_low + wing_ask_high, i.e. the short-fly
    # collects more than the wings cost even at the worst executable prices.
    for a, b, c in zip(ordered, ordered[1:], ordered[2:]):
        ka, kb, kc = _f(a.get("strike")), _f(b.get("strike")), _f(c.get("strike"))
        if None in (ka, kb, kc):
            continue
        if abs((kb - ka) - (kc - kb)) > 1e-6:   # unequal spacing: not a clean fly
            continue
        wl_ask, body_bid, wr_ask = _f(a.get("ask")), _f(b.get("bid")), _f(c.get("ask"))
        if None in (wl_ask, body_bid, wr_ask):
            continue
        if 2.0 * body_bid > wl_ask + wr_ask + 1e-9:
            convexity_violations += 1
    shape_violations += convexity_violations

    valid_count = len(usable)
    quote_coverage = valid_count / total
    timestamp_coverage = timestamped / max(1, valid_count)
    freshness_rate = ((timestamped - stale) / timestamped) if timestamped else None
    spread_rate = max(0.0, (valid_count - wide) / max(1, valid_count))
    unlocked_rate = max(0.0, (valid_count - locked) / max(1, valid_count))
    depth_rate = depth_covered / total
    greek_rate = greek_covered / total
    shape_rate = max(0.0, 1.0 - shape_violations / max(1, valid_count - 1))

    # Quality is not an additive signal. This score describes the reliability of
    # chain-dependent features and is intended to multiply/cap those components.
    components = {
        "quote_coverage": (0.20, quote_coverage),
        "freshness": (0.20, freshness_rate),
        "spread": (0.20, spread_rate),
        "unlocked_quotes": (0.10, unlocked_rate),
        "depth": (0.10, depth_rate),
        "greeks": (0.10, greek_rate),
        "shape": (0.10, shape_rate),
    }
    measured = {k: (w, v) for k, (w, v) in components.items() if v is not None}
    measured_weight = sum(w for w, _ in measured.values())
    score = 100.0 * sum(w * v for w, v in measured.values()) / measured_weight
    score = round(max(0.0, min(100.0, score)), 1)
    score_confidence = round(measured_weight * 100.0, 1)
    assessment_confidence = "HIGH" if score_confidence >= 95 else "LIMITED" if score_confidence >= 75 else "LOW"
    grade = "HIGH" if score >= 85 else "ACCEPTABLE" if score >= 70 else "DEGRADED" if score >= 50 else "LOW"

    # A high renormalized score cannot pass if freshness is wholly unmeasurable.
    gate_passed = (
        score >= 70 and score_confidence >= 90 and crossed == 0
        and quote_coverage >= 0.70 and locked < valid_count
    )

    warnings: List[str] = []
    if crossed: warnings.append(f"{crossed} crossed quote(s) excluded.")
    if locked: warnings.append(f"{locked} locked quote(s) reduced executable-market quality.")
    if missing_quote: warnings.append(f"{missing_quote} contract(s) lacked a complete bid/ask.")
    if timestamped == 0:
        warnings.append("Quote freshness was unmeasurable because no quote timestamps were supplied.")
    elif timestamped < valid_count:
        warnings.append(f"Quote freshness was measurable for only {timestamped} of {valid_count} usable contracts.")
    if stale: warnings.append(f"{stale} timestamped quote(s) exceeded {max_quote_age_seconds:g}s age.")
    if wide: warnings.append(f"{wide} quote(s) exceeded {max_spread_pct:g}% spread.")
    if shape_violations: warnings.append(f"{shape_violations} vertical price-shape violation(s) detected.")
    if not gate_passed: warnings.append("Derived chain metrics should be suppressed or confidence-capped.")

    return {
        "available": True, "version": CHAIN_QUALITY_VERSION,
        "score": score, "score_confidence_pct": score_confidence,
        "assessment_confidence": assessment_confidence,
        "grade": grade, "gate_passed": gate_passed,
        "valid_contract_count": valid_count, "total_contract_count": total,
        "quote_coverage_pct": round(quote_coverage * 100, 1),
        "timestamp_coverage_pct": round(timestamp_coverage * 100, 1),
        "fresh_quote_pct": None if freshness_rate is None else round(freshness_rate * 100, 1),
        "freshness_unavailable_reason": (
            "No usable contract included quote_age_seconds or a parseable source timestamp."
            if freshness_rate is None else None
        ),
        "acceptable_spread_pct": round(spread_rate * 100, 1),
        "unlocked_quote_pct": round(unlocked_rate * 100, 1),
        "depth_coverage_pct": round(depth_rate * 100, 1),
        "greeks_coverage_pct": round(greek_rate * 100, 1),
        "crossed_quote_count": crossed, "locked_quote_count": locked,
        "stale_quote_count": stale, "wide_spread_count": wide,
        "missing_quote_count": missing_quote, "shape_violation_count": shape_violations,
        "convexity_violation_count": convexity_violations,
        "measurable_components": list(measured.keys()),
        "unmeasurable_components": [k for k, (_, v) in components.items() if v is None],
        "thresholds": {"max_quote_age_seconds": max_quote_age_seconds,
                       "max_spread_pct": max_spread_pct, "minimum_gate_score": 70.0,
                       "minimum_score_confidence_pct": 90.0},
        "warnings": warnings,
    }

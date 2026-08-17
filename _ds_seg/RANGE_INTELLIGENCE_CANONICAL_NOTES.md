# APEX — Range Intelligence: canonical Morning Brief context

Fixes the pathologies in the screenshot (put wall 7700 shown as the projected
LOW zone 71pts below spot, 99% range used + HIGH exhaustion pre-open, a
separately-recomputed expected move) by making Range Intelligence read the SAME
canonical session context as the Morning Brief and treating confluence levels as
supplements to — not replacements for — the expected-move envelope.

## The six corrections (all implemented + tested)
1. One authoritative spot + expected move: consumes canonical {spot, em_low,
   em_high} from the Morning Brief; only falls back to a VIX-derived move when
   canonical is absent (flagged EXPECTED_MOVE_DERIVED_FROM_VIX, never silent).
2. Levels separated by purpose: expected_session_range, immediate_reaction_zones,
   intermediate_targets, expansion_targets, tail_risk_levels.
3. Envelope-constrained selection: a candidate >~10% of envelope width outside
   the envelope is excluded from the normal range and classified EXPANSION_TARGET
   / TAIL_RISK_LEVEL / SECONDARY_RESISTANCE / SECONDARY_SUPPORT. The 7700 put wall
   becomes a TAIL_RISK_LEVEL, not the low zone.
4. Pre-open range-used disabled: before a real RTH high/low exist, range_used =
   None (method WAITING_FOR_RTH), exhaustion = NOT_EVALUATED; upside/downside
   remaining are measured from the expected-move envelope.
5. Degraded gating: when runtime is degraded, the route preserves the last valid
   projection, marks stale inputs, and withholds new range/exhaustion conclusions
   (never silently substitutes incomplete clusters for the canonical move).
6. Presentation aligned: the dashboard band renders four sections — Expected
   Session Range, Immediate Reaction Zones, Expansion Targets, Tail-Risk Levels —
   plus a degraded banner and N/A / Not-evaluated states.

## Files (6)
- engine/range_intelligence.py            — canonical/runtime params; envelope-
                                             constrained classification; gating.
- engine/range_routes.py                  — canonical_provider + runtime_provider;
                                             last-valid preservation when degraded.
- app.py                                  — wires _ri_canonical (Morning Brief
                                             snapshot) + _ri_runtime (health).
- templates/apex_os.html                  — four-section RI band + render().
- tests/test_range_intelligence_canonical.py — 11 new tests (the corrections).
- tests/test_range_intelligence.py        — 3 legacy tests realigned to the new
                                             contract (envelope range, no pre-RTH
                                             estimate, envelope-based remaining).

## Verified against the screenshot numbers
spot 7798.99, EM 7771.62–7826.36:
- Expected range: 7771.62–7826.36 (canonical)
- Immediate upper reaction near 7798–7801
- Next upside level: 7816.70 (prev-day high, intermediate)
- Downside tail support: 7700 (TAIL_RISK_LEVEL — no longer the low zone)
- Range used: N/A (WAITING_FOR_RTH) · Exhaustion: NOT_EVALUATED · Runtime: DEGRADED_PREOPEN
Full ratcheted suite: 1858 passed, 0 failed.

## Apply
./apply_range_intelligence_canonical.sh /path/to/apex-engine   (verifies wiring +
no revert of prior features), then branch + PR (main is protected).
Bump the apex_os asset cache-buster so the new RI band loads immediately.

# APEX 11.0C — Live Decision Intelligence

**Status:** complete. Full suite **668 passed / 0 failed** (was 650; +18).
**Phase goal (from the roadmap):** build the modules that rely on CURRENT market
state rather than historical claims — "immediate user value while remaining
statistically honest."

---

## What was already there

Two of the four Phase 11.0C modules already existed and are on the bus:

- **Module 2 (Evidence Engine)** → `engine/dashboard_evidence.py`
- **Module 10 (Trade Coach)** → `engine/trade_coach.py` (already a bus field)

So 11.0C added the two genuinely missing ones. I checked before building to avoid
a second copy of either.

## Module 3 — Probability Distribution Engine

Replaces a single directional bias with a distribution over five session outcomes:

```
Balanced Auction   64%        (positive gamma, compression)
Moderate Selloff   11%
Moderate Rally     11%
Trend Selloff       7%
Large Rally         7%
```

**Structural, not historical.** The probabilities are a transform of the CURRENT
bus state — gamma regime, auction, trend, flow, volatility — not a frequency count
over past sessions. The payload says so (`basis: "structural_current_state"`) so the
number is never mistaken for a backtested edge. Historical frequencies are 11.1 and
need production history this engine doesn't have.

**Honest by construction:**
- Sums to 1.0 (softmax over scenario scores).
- **Never collapses to a near-certainty.** Scores are tanh-squashed before softmax,
  so however many signals align, a strong tilt reads ~65% for its directional
  group, not 95%. A 0DTE session is never 100% one outcome.
- **Widens toward uniform when evidence is weak** — no-evidence returns 20% each and
  flags `distribution_is_informative: false`, an honest "we don't know" rather than
  a fake-confident spike.
- Carries an evidence trail: every scenario score names the live field that moved it.

**Directional correctness verified:** strong bull → 67% bullish group, strong bear →
67% bearish, positive-gamma → 64% balanced, conflicting signals → not informative.

## Module 8 — Confirmation Scanner

Monitors ES, SPY, VIX, VVIX, breadth (ADD/TICK), sector rotation, yields, the dollar
— and reports whether they confirm or diverge from the SPX decision already made.

**The one hard rule, enforced structurally:** this scanner may only STRENGTHEN or
WEAKEN confidence. It never originates a direction and never replaces SPX. The SPX
direction is an *input*; with none supplied, the scanner returns a neutral 1.0 with
every asset marked "nothing to confirm" — it cannot manufacture a lean of its own.
This is tested across every asset combination.

**Bounded, asymmetric multiplier [0.75, 1.15]:** confirmation nudges confidence up a
little (agreement is the base case); divergence pulls down more (disagreement is
information). It can never zero a trade or double it.

**Correct inversions:** VIX/VVIX up is bearish for SPX (confirms a bear view,
diverges from a bull view); rising yields and dollar are equity headwinds. Verified.

## Files

**Added:**
- `engine/probability_distribution.py` + `_routes.py`
- `engine/confirmation_scanner.py` + `_routes.py`
- `tests/test_probability_distribution.py` (10), `tests/test_confirmation_scanner.py` (8)

**Modified:** `app.py` — registers both routes behind non-fatal import guards,
read-only closures over `STATE["last_result"]` under `STATE_LOCK`, same pattern as
every other feature engine.

## Endpoints (read-only)

| Route | Reports |
|---|---|
| `/api/probability_distribution` | live scenario distribution + evidence trail |
| `/api/confirmation_scan` | confirm/diverge verdict + bounded multiplier |
| `…/health` (both) | version ping |

## Tests

| Concern | Tests |
|---|---|
| distribution sums to 100, all 5 scenarios present | 2 |
| **never a near-certainty** | 1 |
| strong bull/bear lean correctly; positive gamma → balance | 3 |
| no-evidence → uniform + not-informative | 1 |
| **basis is structural, never historical** | 1 |
| evidence trail explains the distribution | 1 |
| empty bus safe | 1 |
| **no SPX view → scanner stays neutral (can't lead)** | 1 |
| **multiplier always in [0.75, 1.15]** | 1 |
| confirmation strengthens / divergence weakens | 2 |
| **VIX correctly inverted** | 1 |
| divergence surfaced, not hidden | 1 |
| no assets → confidence unchanged; never raises | 2 |

## Design notes

1. **Neither module writes anything.** Both are pure read-only consumers of the bus,
   consistent with the whole feature-engine layer. Nothing here accumulates history —
   that's deliberate; 11.1 is where history lives.
2. **The scanner's multiplier is not yet applied to a live confidence number.** It's
   computed and exposed; wiring it into the displayed confidence is a UI decision for
   Mission Control. The bounded, modifier-only contract means it's safe to apply
   wherever it's consumed.
3. **The probability engine's directional_lean** gives consumers that still want one
   number a signed lean, without hiding the full distribution behind it.

## Where 11.0 stands

- 11.0A Release Manager / data integrity ✓
- 11.0B Chain quality as a pricing input ✓
- 11.0C Live decision modules (2, 3, 8, 10) ✓

That completes the live-state half. Everything remaining (Modules 1, 4, 6, 7, 9, 11 —
Trade Finder, Similarity, Strategy stats, Kelly, Research Lab, Calibration) is Phase
11.1 and gated on accumulated production history. `/api/system/integrity` will report
`statistics_supportable: true` once the stores it names have rows.

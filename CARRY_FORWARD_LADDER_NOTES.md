# APEX 66.6.0 — Carry-Forward Levels Ladder

A "Levels" tab in the APEX dashboard that renders the carry-forward levels as a
spot-relative ladder — the SAME numbers as the morning/evening brief, because it
reads the same source (DailyKeyLevels structured payload). No copy-paste.

## Files (6)
NEW:
- engine/carry_forward_ladder.py        — pure builder: overhead / value-shelf / below,
                                           key pivots, nearest S/R, neutral one-line map.
- engine/carry_forward_ladder_routes.py — GET /api/carry-forward-ladder (+ /api/levels-ladder).
- tests/test_carry_forward_ladder.py    — 8 unit tests.
CHANGED:
- app.py                 — import guard + route registration (mirrors breadth_regime);
                           structured_provider reads the cached Morning Brief cheaply
                           (no provider I/O, no LLM).
- templates/apex_os.html — "Levels" tab button + pane + scoped CSS.
- static/js/apex_os.js   — lazy loader + renderer; loads on tab open + Refresh button.

## How it works
- The route reshapes already-computed structured levels; it never generates a brief,
  so it's cheap enough to hit on every refresh.
- Classifies each level vs spot: overhead (resistance, red), value shelf hugging price
  (blue, within ~0.1% of spot), below (support, green). Folds in the expected-move
  envelope; extracts gamma flip / put wall / call wall; marks nearest resistance/support;
  writes a neutral map summary (never a trade call).
- Until a Morning Brief exists for the session, the panel shows
  "generate the Morning Brief for this session." That's expected — the brief is what
  populates the cached levels. (Building levels on demand without a brief is a follow-on:
  it would mean wiring the provider path into the route, which is heavier.)

## Verified
- app boots: 884 routes; /api/carry-forward-ladder + /api/levels-ladder registered;
  CARRY_FORWARD_LADDER_AVAILABLE = True; authed endpoint 200 with graceful empty state.
- Dead-code guard + version-drift guard: pass (modules reachable via app.py; manifest and
  registry both remain 66.5.0 and agree — no version bump needed for an additive feature).
- Full ratcheted suite: 1840 passed, 0 failed (was 1832; +8 new tests, no regressions).

## Apply
Option A (safest): ./apply_carry_forward_ladder.sh /path/to/apex-engine  (verifies wiring)
Option B: drop the 6 files into place manually, keeping paths.
Then commit, push, deploy. Hard-refresh the dashboard and open the Levels tab.

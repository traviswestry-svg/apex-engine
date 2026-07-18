# APEX 11.0C+ — Mission Control surfaces the live decision modules

**Status:** complete. Backend suite **668 passed / 0 failed** (unchanged — this is a
composition + UI change, no engine logic touched). Render logic verified against the
real endpoint payload.

---

## What this does

11.0C built the Probability Distribution and Confirmation Scanner engines and gave
each its own endpoint. They were exposed but not *visible* — nothing on the actual
workspace showed them. This wires both into Mission Control, the page the operator
already watches, so the live decision intelligence is seen rather than merely
queryable.

No new page. Mission Control already exists (`/apex_os`, consuming
`/api/mission_control`). Adding a separate screen would fragment the UI; instead both
modules join the existing single-poll payload and render as two panels in the
established `.mc-*` visual language.

## Backend — one composition point

`/api/mission_control` now includes `probability_distribution` and `confirmation_scan`,
composed from the same `STATE["last_result"]` bus it already reads. Both are pure
read-only reads — no scan triggered, no external call — so the endpoint's "pure
composition" contract holds. Each is wrapped so a module failure degrades its own
panel to unavailable rather than 500-ing the workspace.

The confirmation scanner's SPX direction is read *off the decision already made*
(`approved_side` → consensus → flow), never formed by the scanner — the modifier-only
contract is preserved across the wiring.

## Frontend — two panels, native to the workspace

**Session Outcomes** — the probability distribution as a horizontal bar spectrum,
ordered bearish → bullish so it reads like a lean. The leading scenario is
emphasised; bars are toned green/blue/red by direction; a `structural · live` badge
states plainly that these are current-state probabilities, not historical
frequencies. When evidence is ambiguous, the note says so instead of implying a
favourite.

**Confirmation** — confirming assets as green ✓ chips, diverging as red ✕ chips, with
the verdict and the bounded multiplier (×0.75–×1.15). When there is no SPX view yet,
the panel says "nothing to confirm — confirmation assets only strengthen or weaken an
existing view" rather than showing a fabricated read. The scanner's refusal to lead
is visible in the UI, not just the engine.

## Render logic — verified

The two render functions were run against the real endpoint payload in a headless DOM:

```
PROBABILITY: 5 bars, spectrum-ordered, leader marked, BULLISH lean (green), note set
CONFIRMATION: 4 confirm chips, STRONGLY CONFIRMED, ×1.15 (green)
NO-SPX-VIEW: verdict NEUTRAL, ×1.00, "nothing to confirm" — refuses to lead
EMPTY: idle placeholder, no crash
```

## Files

**Modified:**
- `app.py` — `/api/mission_control` composes both modules (non-fatal, read-only)
- `static/js/apex_os.js` — `renderMcProbability`, `renderMcConfirmation`, called at
  the end of `renderMissionControl`
- `templates/apex_os.html` — two panels after the intelligence strip
- `static/css/apex_os.css` — scoped `.mc-prob` / `.mc-confirm` styles, responsive

## Design notes

1. **Bumping asset version.** These changes touch `apex_os.js` and `apex_os.css`;
   ensure `STATIC_ASSET_VERSION` is incremented on deploy so browsers pick up the new
   assets rather than cached ones.
2. **The multiplier is displayed but not yet auto-applied to the headline confidence
   number.** Showing it first, beside the SPX decision, lets the operator see the
   adjustment before it's baked in — a deliberate half-step. Wiring it into the
   displayed confidence is a small, separate change once you've watched it behave on
   live data.
3. **Screenshots weren't captured** — booting the full app plus Chromium exceeded the
   sandbox time limit. The render logic was instead verified directly against the real
   payload (above). Worth an eyeball on a live deploy to confirm spacing.

# APEX 8.0 — Piece One: Mission Control homepage + four-layer navigation

The first, zero-risk step of the "execution operating system" rework: consolidate
what you already compute into one clear decision-first structure. **No new
probability claims** — every number shown is real data already in the payload.

## What this piece does
1. **Mission Control is the homepage.** Root `/` already redirects to `/apex_os`,
   which defaults to the Mission Control tab. Confirmed, unchanged.
2. **Four-layer navigation** replaces the flat 8-tab row:
   - **Decision** → Mission Control (emphasized)
   - **Execution** → Execution
   - **Institutional Intelligence** → Analysis · Chart · Flow · Story · Tape
   - **Analytics & Learning** → Replay · Signal Log
3. **New Execution Intelligence tab (Layer 2)** built entirely from existing
   `execution_intelligence` + `risk` engine output:
   - Stage + Execution Quality + timing header
   - THE TRADE: entry / stop / T1 / T2 / R:R / contract / risk points / invalidation
   - Five execution signals (exhaustion, absorption, gamma wall, pressure, delta)
     with strength bars and color-coded borders
   - WHY bullets and EXIT PLAN
   - **EDGE STATISTICS marked "AWAITING OUTCOME DATA"** — win rate / avg hold /
     max adverse excursion / sample size are shown as pending, never fabricated.
     They populate in Piece Three, once the outcome-logging spine exists.

## Deploy (upload/overwrite in place)
```
templates/apex_os.html      → templates/apex_os.html
static/js/apex_os.js        → static/js/apex_os.js
static/css/apex_os.css      → static/css/apex_os.css
app.py                      → app.py   (see note below)
```

### Important — about app.py
`app.py` here is **unchanged from the System Mode delivery** in the prior message
(holiday awareness, `system_mode()`, version consistency). It's included so this
package is self-contained. The three frontend files carry **both** the System Mode
server-render **and** this four-layer nav change (they're the same files).

- If you already deployed the System Mode `app.py`: just upload the 3 frontend files.
- If you have not: upload all 4. The template's `{{ mode }}` block degrades safely
  if `app.py` is older, but you'll want the System Mode app.py for the meaningful
  first-paint banner.

## How it works under the hood
- The existing `initTabs()` binds any `.tab-btn[data-tab]`, so grouping the buttons
  under `.layer-group` containers required no JS change to tab switching.
- `renderExecutionIntel(d)` is wired into the scan fan-out (`_renderAll`) right
  after `renderStory`, so the Execution tab updates every scan like the others.
- All new CSS is scoped under `.layer-*` and `.exec-*`, derived from your existing
  design tokens — no changes to existing selectors.

## Verified
- `apex_os.js` passes `node --check`; `app.py` compiles.
- All 9 tab buttons have matching panes (added `exec`).
- Rendered preview (seeded ARMED payload): 4 nav groups, stage ARMED, 78% quality,
  trade levels, 5 signal cards, why/exits, and the pending edge-stats block all
  render correctly.

## Not in this piece (by design)
- Calibrated conviction number and "this setup occurred N times" — those require
  the outcome-logging spine (Piece Two) and realized-trade data (Piece Three).
- Ranked flow tape and the Story "why" upgrade — greenlit separately; honest to
  build next, but not part of the homepage/nav consolidation.

## Suggested next
**Piece Two — the outcome-logging spine:** log every signal with full entry context,
then auto-track MFE/MAE/win after. It's the foundation the Edge Statistics block and
a real conviction number both depend on. Once it's accumulating, the pending cells in
the Execution tab start filling with measured numbers.

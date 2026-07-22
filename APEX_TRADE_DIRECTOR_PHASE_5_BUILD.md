# APEX Trade Director Phase 5 — Institutional Trade Coach

## Built from
APEX Trade Director Phase 4 deployed baseline.

## Added

### Live Institutional Trade Coach
- Converts the active recommendation into a concise, evidence-backed explanation.
- Displays supporting and opposing APEX engines.
- Shows continuation probability, reversal probability, expected remaining move, and the next condition to watch.
- Uses only the existing Trade Director and cached Institutional OS state.

### Recommendation Timeline
- Records the initial manual entry.
- Records material recommendation and Trade Health changes.
- Records manual trims, stop-to-breakeven actions, premium updates, and closure.
- Keeps a bounded 120-event in-memory history for the active trade.

### Ask APEX
- Answers active-trade questions such as:
  - Should I hold?
  - Why did Trade Health drop?
  - What is the biggest risk?
  - Why are you recommending a trim or exit?
  - What changed?
- Answers are deterministic and grounded only in the current position state.

### Post-Trade Review
- Generated when the position is marked closed.
- Reports duration, Trade Health start/peak/close, recommendation count and changes, provisional process score, estimated P/L when premium data is available, and review lessons.
- Outcome calibration is explicitly marked provisional until broker fills and post-exit price paths are synchronized.

## New API routes
- `GET /api/position/coach`
- `POST /api/position/ask`
- `GET /api/position/review`

## Safety and stability
- No broker orders are submitted or modified.
- No new scanners, provider calls, startup tasks, worker threads, or polling processes were added.
- Existing Render stability settings remain unchanged.
- Static asset version bumped to force the Phase 5 dashboard update.

## Validation
- `app.py` compiled successfully.
- Existing Active Trade Director suite: 30 tests passed.
- Phase 5 route/UI presence checks passed.
- Assistant JavaScript passed `node --check`.

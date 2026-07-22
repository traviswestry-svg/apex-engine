# APEX Trade Director — Phase 3

## Added
- Primary Trade Health Engine scored from 0–100.
- Five weighted health factors: Institutional Consensus, Flow/Alignment, Dealer/Gamma, Price Structure, and Risk Discipline.
- Health bands with direct guidance:
  - 95–100: Press the advantage
  - 85–94: Hold confidently
  - 70–84: Manage carefully
  - 50–69: Protect profit
  - Below 50: Exit or reduce
- Improving, stable, or deteriorating health trend with score delta.
- Rolling in-memory health history for the active trade.
- Mobile-responsive health gauge, factor bars, and mini trend chart.
- Phase 3 safety governor that can elevate HOLD to TRIM, PROTECT PROFIT, or EXIT when health deteriorates.

## Stability and safety
- Uses only data already available to the active-position monitor and Phase 2 cached synthesis.
- Adds no provider calls, scanner, scheduled process, import-time work, or background thread.
- Does not place, modify, or close broker orders.
- Health history is bounded to 30 records and resets when the active position is cleared.

## Validation
- `python -m py_compile app.py` passed.
- All 30 Active Trade Director tests passed.

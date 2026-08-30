# APEX 69.8.1 — Premium Discipline Trade Visualization & Learning Readiness Command Center

## Objective
Make the 69.8 evidence and trigger lifecycle operationally visible without changing production decision or execution authority.

## Delivered
- Adds a visual APEX trade/trigger review surface to the Premium Discipline Command Center.
- Plots persisted SPX entry, stop, TP1/TP2/TP3 and the persisted five-minute trigger price path.
- Shows target/stop touches, MFE/MAE, confidence, blockers and canonical grade linkage.
- Distinguishes actionable canonical trades from blocked/observational triggers.
- Adds recent-trigger selection for historical review.
- Shows Trigger Effectiveness and Learning Readiness on the dashboard.
- Shows option-premium fields only when those values were actually persisted with trigger evidence; otherwise reports PREMIUM DATA UNAVAILABLE.

## Authority
The entire 69.8.1 visualization surface is observational/read-only. It cannot change decisions, confidence, eligibility, risk, sizing, targets, execution, calibration policy, broker state, Tick Momentum authority, or Microstructure authority.

## Data Truth
The trade path is constructed only from `trade_trigger_price_observations`. No synthetic candles, synthetic premium, or inferred execution fills are created.

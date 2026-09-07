# APEX 66.9.0 — BPSPX Freshness Governance

Adds fail-closed observation-age governance to Breadth Regime.

## States
- CURRENT_SESSION — fresh observation while market is open.
- PRIOR_SETTLED_SESSION — recent settled observation while market is closed.
- STALE — observation retained for diagnostics but barred from influence.
- DATA_LIMITED — timestamp missing/invalid or no usable observation.

## Authority
Freshness governance does not create trade or execution authority. Stale breadth
has zero horizon weight and cannot modify SCALP, INTRADAY, or SWING decisions.

## Codespaces
No absolute paths or Render-specific assumptions are introduced.

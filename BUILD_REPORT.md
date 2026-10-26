# Adaptive Morning Forecast Calibration — shadow candidate

Base repository: uploaded APEX 69.10.47. Release manifest unchanged.

Includes read-only robust median calibration for prior verified sessions and a walk-forward evaluator. The morning brief emits an INSUFFICIENT_VERIFIED_HISTORY shadow diagnostic by default: it deliberately does not load outcome history on the live request path. No live forecast modification, performance claim, historical backfill, execution change, or automatic promotion.

Offline evaluation requires the operator to supply completed session rows with frozen forecast provenance, spot, expected move, realized high/low, and explicit outcome_complete=true. At least 20 unique prior sessions required. Candidate scaling bounded to 0.75–1.5 and center shift bounded to +/-0.5 sigma. All historical records excluded from own training date; duplicate session dates excluded.

Focused tests: 6 passed. Python compilation passed. Full CI, production load, and historical backtest not run. Do not deploy as an accuracy-improving model without genuine historical walk-forward evidence.

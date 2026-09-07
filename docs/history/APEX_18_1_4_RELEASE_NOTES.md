# APEX 18.1.4 — Adaptive Portfolio Allocation Calibration

Runtime: `11.0.12_ADAPTIVE_PORTFOLIO_ALLOCATION_CALIBRATION`

This release reconciles the deployed baseline with the missing 18.1.3 portfolio-outcome layer and adds governed learning for portfolio allocation.

## Included 18.1.3 capability
- Durable portfolio recommendation ledger
- Exact captured-position replay through the 4:00 PM ET settlement window
- Contract-weighted portfolio P&L and strategy attribution
- Portfolio outcomes, scorecard, and replay endpoints

## 18.1.4 capability
- Immutable portfolio-calibration runs
- Minimum-sample protection
- Bounded recommendations for institutional-score weight, expected-value weight, and bull/bear pairing penalty
- Explicit operator promotion before recommendations become operational
- One active promoted portfolio policy at a time
- Promoted policy applied to portfolio selection and allocation
- Command-center visibility into outcome attribution and calibration governance

The module remains advisory and has no broker execution authority.

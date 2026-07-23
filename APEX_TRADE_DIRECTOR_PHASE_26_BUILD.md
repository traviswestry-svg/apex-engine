# APEX Trade Director Phase 26

## Institutional Performance & Intelligence Command Center

Phase 26 is an observational executive layer above Phases 11–25. It aggregates engine availability, freshness, evidence completeness, archived performance, calibration, drift, governance, and shadow-validation state.

### Capabilities

- Per-engine health scoring with GREEN/YELLOW/RED status
- System Confidence Index (SCI)
- Institutional performance scorecard
- Expectancy, win rate, profit factor, realized P/L, and drawdown
- Confidence-calibration diagnostics
- Rolling drift detection
- Engine effectiveness ranking
- Policy and shadow-validation pipeline summary
- Executive dashboard and diagnostic API

### Safety

Phase 26 cannot modify strategy, policy, risk, authorization, lifecycle management, live configuration, or broker orders. All outputs are observational and advisory.

### API

- `GET /api/command-center/system-health`
- `GET /api/command-center/performance`
- `GET /api/command-center/scorecards`
- `POST /api/command-center/diagnostics`

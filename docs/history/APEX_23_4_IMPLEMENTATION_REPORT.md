# APEX 23.4 — Continuous Learning & Confidence Calibration

Release: `16.4.0_CONTINUOUS_LEARNING_CONFIDENCE_CALIBRATION`

## Implemented

- Sanitized matured-outcome ingestion with immutable duplicate protection.
- Confidence calibration buckets, Brier score, and mean absolute calibration error.
- Performance tracking by playbook, regime, and forecast scenario.
- Recent-versus-prior drift detection.
- Bounded advisory weight recommendations requiring human approval.
- Mission Control learning status and diagnostics drill-down.
- Read-only learning APIs plus a restricted outcome-recording API.

## Safety

The release does not automatically mutate production weights, displayed production confidence, risk limits, execution permissions, or broker state. Recommendations remain pending until explicitly reviewed outside this engine.

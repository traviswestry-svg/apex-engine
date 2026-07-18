# Readiness, Limitations, and Disabled Features

## Historical-data readiness

Initial production status is **COLLECTING** because the repository contains no validated governance outcomes in the new evidence store. Default calibration threshold is 50 verified graded recommendations and can be configured with `APEX_MIN_GRADED_HISTORY`.

## Similarity status

The feature-vector schema, hashing, storage, nearest-neighbor retrieval, provenance, and look-ahead guard are operational. Similar-outcome performance, MFE, MAE, hold time, invalidation frequency, regime-conditioned performance, and family comparisons remain unavailable until real graded matches meet evidence thresholds.

## Adaptive-learning status

Initial status is **DISABLED**. Candidate records can be created for offline work, but approval for shadow mode is blocked until validated history passes minimum thresholds. Production promotion is never automatic.

## Intentionally disabled pending evidence

- Production confidence calibration
- Reliability diagrams, Brier score, ECE, precision, and recall as valid production metrics
- Historical expectancy and drawdown claims
- Similar-setup performance claims
- Automatic engine-weight changes
- Automatic confidence or conviction recalibration
- Autonomous recommendation suppression or promotion
- Self-modifying strategy logic
- Live unsupervised deployment
- Automatic candidate promotion
- Automatic calibration-artifact promotion

## Known limitations

- The governance layer is SQLite-first to match the current repository architecture; high-volume multi-instance deployments should migrate the same contracts to a managed relational database.
- Shadow-result capture and drift-event writing have storage contracts but require real production orchestration to populate them.
- Strategy findings remain a research shell until real history exists.
- Confidence intervals are intentionally reported unavailable until a configured statistical method and adequate sample are present.

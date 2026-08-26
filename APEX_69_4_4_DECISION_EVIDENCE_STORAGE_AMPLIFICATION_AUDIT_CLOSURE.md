# APEX 69.4.4 — Decision Evidence Storage Amplification Audit & Closure

## Finding
Production storage audit showed `decisions` consuming ~643 MB for 721 rows while `price_samples` consumed <1 MB. The canonical evidence writer persisted the complete nested `institutional_decision_object` inside every `decisions.snapshot_json` row despite the historical snapshot contract being intended to be bounded. That object contains repeated narrative, evidence graph, provider, lifecycle and provenance structures and is not required in full by downstream grading.

## Closure
69.4.4 keeps the contemporaneous in-memory snapshot unchanged for dynamic-state context and Decision Outcome Attribution, but writes a bounded canonical projection to `decisions.snapshot_json`. The projection preserves decision identity, direction/action, eligibility, price/confidence, setup, horizons/regimes, observational flags and a compact compatibility surface of the institutional decision object. It records the SHA-256 and byte size of the source snapshot plus the omitted institutional-object field names for traceability.

The storage audit now reports aggregate snapshot bytes, average/max decision snapshot size, bounded largest/latest row sizes, top-level byte contributors and repeated-value hashes without exposing payload contents or mutating historical rows.

## Explicitly not implemented
- No automatic rewrite, migration, deletion or compaction of the existing 721 historical decision rows.
- No VACUUM.
- No change to trade decisions, confidence, grading eligibility, attribution thresholds, execution authority, adaptive calibration, or learning thresholds.
- No fabrication or synthetic historical evidence.

A future operator-approved historical compaction may be considered only after production verifies the 69.4.4 projection on new rows and a separate migration plan proves semantic equivalence and rollback safety.

# APEX 69.4.3.1 — Storage Retention Audit & Safe Maintenance Guardrails

Operational storage closure only. Adds governed classification and explicit operator maintenance for SQLite WALs, aged corrupt quarantine backups, and mature forward price samples. Canonical decisions, grading results, flow features, excursion evidence, calibration evidence, active databases, and learning thresholds are preserved. No automatic deletion and no automatic VACUUM are introduced.

The evidence pipeline's `price_samples` table is forward-grading support data, not the canonical graded outcome. Rows older than the configured retention window may be removed only when they are also older than the earliest pending decision. Deletion frees pages for SQLite reuse; VACUUM is deliberately prohibited under low-disk conditions.

Aged `*.corrupt-*` files created by DB resilience are classified as quarantined non-active artifacts. Cleanup requires an explicit operator invocation and acknowledgement. WAL maintenance uses SQLite checkpointing rather than unlinking WAL/SHM files.

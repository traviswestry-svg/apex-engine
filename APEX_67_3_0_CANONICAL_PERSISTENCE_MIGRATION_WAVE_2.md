# APEX 67.3.0 — Canonical Persistence Migration Wave 2

Migrates high-consequence decision, learning, calibration, promotion, governance,
and evidence stores to `engine.canonical_persistence.connect`.

## Migrated modules
- adaptive_learning
- learning_calibration
- offline_weight_optimization
- adaptive_intelligence
- institutional_validation_promotion_v255
- institutional_evidence_graph
- strategy_promotion_governance
- trade_director_institutional_learning
- prediction_confidence_calibration
- institutional_learning_engine
- production_governance
- decision_evidence_pipeline
- decision_intelligence_core
- decision_provenance
- institutional_evidence
- adaptive_refusal_calibration
- continuous_learning_calibration
- trade_director_performance_calibration
- institutional_decision_review
- trade_director_institutional_evidence

## Guardrails
No database schema changes. No database path changes. No decision/model logic
changes. No execution-authority changes. Existing callers retain the same
connection and transaction semantics while gaining the canonical WAL, busy
timeout, foreign-key, row-factory, and resilience policy.

Wave 3 should target execution/risk/position stores rather than research/reporting.

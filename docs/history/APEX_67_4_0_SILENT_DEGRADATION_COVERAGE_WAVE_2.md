# APEX 67.4.0 — Silent-Degradation Coverage Wave 2

Extends 67.1 structured degradation recording into high-consequence fallback paths.

## Instrumented
- Execution Intelligence risk-limit fallback
- Execution Intelligence entry optimization, sizing, contract, and liquidity subcomponents
- Position Sizing risk-limit fallback
- Daily Key Levels HLCE enrichment fallback
- Signal Evaluator outcome callback failure
- Learning Calibration store/proposal/signal-provider fallback
- Institutional Validation & Promotion governance-audit failure
- Range Intelligence provider/capture fallbacks
- Execution OS current-state/session/risk provider failures
- HLCE collector prune maintenance failure

## Guardrails
The original fallback behavior is preserved. This build only records that the
fallback happened, what fallback was used, and whether decision authority was
suppressed. The recorder remains best-effort and cannot raise into callers.

No trading logic, risk limits, schemas, database paths, or execution authority
are changed.

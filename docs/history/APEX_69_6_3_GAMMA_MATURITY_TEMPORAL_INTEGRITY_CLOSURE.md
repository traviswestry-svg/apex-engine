# APEX 69.6.3 — Gamma Maturity Temporal Integrity Closure

## Scope
- Preserve signed DTE instead of clamping expired expirations into 0DTE.
- Exclude expired expirations from current maturity-concentration evidence while retaining them for observability.
- Add an explicit `as_of` date to the QuantData gamma builder for deterministic replay/tests.
- Anchor the 69.6.0 maturity regression to its intended 2026-08-28 snapshot date.

## Guardrails
No execution-authority change, no fabricated gamma, no historical rewrite, no threshold relaxation, and no leakage from future maturities.

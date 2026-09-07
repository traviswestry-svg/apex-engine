# APEX 68.1.1 — Intraday Governance CI Regression Fix

- Adds a composition-level contract backstop ensuring an authoritative
  Intraday conflict is always returned as `CANONICAL_SESSION_GOVERNED`.
- Preserves the raw conflicting direction for diagnostics.
- Keeps confidence capped at 50 and trade focus fail-closed at `NO_TRADE`.
- Updates the legacy regression expectation while retaining `CONFLICT` for
  Scalp and Swing contexts that oppose the canonical decision.

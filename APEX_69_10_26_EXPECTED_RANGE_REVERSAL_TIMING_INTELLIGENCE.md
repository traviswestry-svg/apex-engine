# APEX 69.10.26 — Expected Range Reversal Timing Intelligence

## Purpose

APEX now treats the canonical Expected Session Range as a **reversal search zone**, not as an exact top/bottom or automatic entry trigger.

This build is designed for the observed SPX pattern where price can reach or exceed the expected range, spend one or more hours rotating near the extreme, and only later produce the actual reversal expansion. The objective is to prevent a low-delta 0DTE contract from being selected solely because price touched the expected range boundary.

## Canonical range extension framework

For an expected range with low `L`, high `H`, and full width `R = H - L`, APEX publishes:

- Upper +10%: `H + 0.10R`
- Upper +20%: `H + 0.20R`
- Upper +30%: `H + 0.30R`
- Lower -10%: `L - 0.10R`
- Lower -20%: `L - 0.20R`
- Lower -30%: `L - 0.30R`

For the 2026-10-01 example range `7613.03–7690.05` (77.02 points):

- Upper extensions: 7697.75, 7705.45, 7713.16
- Lower extensions: 7605.33, 7597.63, 7589.92

The original Expected Session Range remains the source of truth. These extension bands do not modify or replace the Morning Brief canonical envelope.

## Reversal states

The new advisory layer exposes the following states:

- `RANGE_MONITOR`
- `EXHAUSTION_WATCH`
- `EXTENSION_ACTIVE`
- `REVERSAL_DEVELOPING`
- `REVERSAL_CONFIRMED_ADVISORY`

`REVERSAL_CONFIRMED_ADVISORY` is not trade authorization and does not change execution authority.

## Reversal evidence

The score is built only from evidence already available in APEX. Missing evidence is not synthesized.

- Range location: 20 points
- Return-through-envelope rejection proxy: 20 points
- Order-flow shift: 20 points
- Structure shift: 15 points
- Absorption: 10 points
- Displacement away from the session extreme: 15 points

The return-through-envelope event is explicitly labelled a conservative **proxy** for a liquidity sweep/rejection. APEX does not claim that resting liquidity was actually executed unless a separate authoritative source proves it.

## Time-at-extreme intelligence

The range endpoint now attaches read-only timing evidence from the canonical `price_samples` store:

- first expected-range edge touch
- minutes since first touch
- observed minutes continuously outside the expected range
- sample count

Only genuine stored price samples are used. Inter-sample gaps are capped at 300 seconds when calculating observed dwell time so scanner outages cannot fabricate long periods of extreme occupancy.

## Contract-horizon advisory

This build adds a strategy-alignment advisory for the reversal module:

- Early/unconfirmed edge, extension, or exhaustion watch: **2DTE, 0.50–0.65 delta** advisory
- Confirmed advisory reversal: **1DTE, 0.45–0.60 delta** advisory
- No active edge reversal: no contract promotion

This is an informational horizon-selection aid only. It does not place orders, authorize trades, or override any risk/execution guardrail.

## Dashboard

The Institutional OS Range Intelligence panel now shows:

- reversal timing state
- active edge
- current extension percentage/points
- normalized evidence score
- DTE/delta advisory
- upper/lower 10/20/30% extension bands
- first edge touch and observed extreme dwell time
- interpretation text

## Governance

The build is additive and advisory-only:

- canonical Expected Session Range remains unchanged
- range boundary is never treated as an automatic entry signal
- no synthetic structure or liquidity evidence
- no broker mutation
- no automatic order submission
- no trade-decision authority change
- no execution-authority change

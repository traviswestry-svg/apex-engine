# APEX forward provenance — opt-in research patch

## Intent and evidence boundaries

This patch introduces a separate, forward-only SQLite receipt ledger for **new** scanner gamma computations, gamma snapshot inserts, and decision inserts. It does **not** modify historical `decisions` or `gamma_observational_snapshots` schemas or backfill 3,569 historical records. It does not alter scoring, order routing, signal gates, calibration, or execution authority.

**IMPORTANT:** The ledger stores *self-reported process claims*, not independently authenticated origin. `RENDER_GIT_COMMIT`, if present, is a claim, not cryptographically verified by this patch. Hash chaining detects some accidental alterations and establishes local ordering, but does not protect against an administrator rewriting the ledger. Authenticated provenance would require external deploy attestation plus off-host/checkpointed hash-chain anchors.

## Default-safe activation

Off by default. For an isolated test deployment, configure `APEX_FORWARD_PROVENANCE_ENABLED=1` and optionally `APEX_FORWARD_PROVENANCE_DB=/path/to/isolated.db`. Default path uses the normal persistent data directory and `apex_forward_provenance.db`. Do **not** activate on production before a controlled staging rehearsal and explicit deployment review.

When enabled, these events are emitted:

- `GAMMA_CALCULATED`: emitted in the scanner/background call path immediately after the QuantData gamma function returns, with a fresh UUID and market-state fingerprint. HTTP presentation calls are not instrumented.
- `GAMMA_PERSISTED`: emitted only when a canonical gamma snapshot was actually newly inserted. It carries the prior UUID when the calculation receipt succeeded.
- `DECISION_PERSISTED`: emitted only for a newly inserted decision. It links to the preceding gamma calculation *only* if the sidecar contains one matching gamma-persistence receipt and one calculation receipt with the same runtime boot and PID. Otherwise the linkage is explicitly `UNVERIFIED`.

`event_time` and `inserted_at` are local timestamps captured by this ledger; `decision_observed_at` remains separate; provider timestamps are not manufactured. Events carry runtime boot ID, PID, release manifest version and optional Render env SHA/service claims. All statuses remain `RUNTIME_CLAIM_UNVERIFIED` or `UNVERIFIED`; no promotion is performed.

Receipts are append-only at the SQLite trigger level and hash chained. The sidecar is *not* atomically committed with the existing gamma and decision databases. A crash or write error can produce a persisted source record with no receipt; this remains unauthenticated and must not be promoted. Duplicate inserts do not generate new receipts. A child process fork will not reuse a parent's boot claim.

## Validation

```bash
PYTHONPATH=. python -m unittest tests.test_forward_provenance -v
PYTHONPATH=. python -m unittest discover -s tests -p 'test_apex_stage3b315_gamma_receipt_provenance_correlation.py' -v
```

For an isolated ledger health check (read-only):

```python
from engine.forward_provenance import verify_chain
print(verify_chain(path='/path/to/isolated.db'))
```

No audit should consider `verify_chain()['ok']` sufficient to establish authentic runtime identity. No automatic evidence-class migration is implemented.

## Required before production promotion

1. Staging exercise on simulated QuantData data and isolated persistent storage.
2. Observe receipts, duplicates, process restarts, disconnected gamma references, and receipt write failures.
3. Deploy verified Git SHA / service ID with independently captured, time-bounded Render deployment attestations.
4. Publish immutable chain-head checkpoints to an independent store, retaining evidence of the signing identity.
5. Implement verifier and strict eligibility gate that never uses event-time proximity, release-only equality, or retrospectively inferred commits as proof of origin.

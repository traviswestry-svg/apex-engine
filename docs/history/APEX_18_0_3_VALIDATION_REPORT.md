# APEX 18.0.3 — Validation Report

## Automated validation

- Targeted operational-health, health-state, release-manager, and release-route tests: 19 passed.
- Complete repository regression suite: 909 passed, 0 failed.
- Python compilation passed for `app.py` and `engine/release_manager.py`.
- `/health` smoke test returned HTTP 200.

## Behaviors pinned by tests

- `updated_at` cannot be null, including closed-session cold start.
- The payload explains whether `updated_at` represents a completed scan or current status generation.
- Deployment build, Git SHA, and deployed timestamp are surfaced from environment metadata.
- Scan age and scanner-heartbeat age are reported separately.
- Source latency remains null when not measured rather than being fabricated.
- Rich source records retain measured latency and last-success timestamps.

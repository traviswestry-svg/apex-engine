# APEX 66.5.0 — Breadth Exhaustion & Recovery Engine

- Adds true BPSPX condition classification without substituting a price proxy.
- Distinguishes capitulation, early recovery, confirmed recovery, deterioration, and broad risk states.
- Applies separate scalp, intraday, and swing influence weights.
- Keeps BPSPX advisory-only: an extreme reading cannot create an entry or block a valid scalp.
- Fails closed as `DATA_LIMITED` when a canonical BPSPX observation is unavailable.
- Adds dashboard visibility and complete status/diagnostic endpoints.

## TradingView BPSPX feed

Create a once-per-bar-close alert on the daily `BPSPX` chart and send it to the
existing `/tv_signal` webhook using this payload:

```json
{"secret":"YOUR_EXISTING_WEBHOOK_SECRET","source":"APEX_BREADTH","ticker":"BPSPX","bpspx":{{close}}}
```

APEX recognizes this as breadth data, not a trade signal. Until the first valid
observation arrives, the dashboard intentionally displays `DATA LIMITED`.

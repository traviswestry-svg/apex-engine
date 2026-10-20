# APEX 69.10.39 — TradersPost Paper Execution (candidate, not deployment-certified)

## What is implemented

- Separate `/api/paper/traderspost/dispatch` protected by an independent operator token.
- Default-disabled, SPX index-options-only paper dispatch with an operator paper-subscription attestation, governed/human approval assertions, strict quantity, debit, session and maximum three entries per ET day.
- E*TRADE mutation endpoints in `engine/execution/trade_routes.py` default to blocked unless explicitly re-enabled by a *separate* live-routing configuration. Paper dispatch refuses to run when live E*TRADE routing is enabled.
- Persistent SQLite signal IDs; HTTP acceptance does not prove a fill. Unknown delivery is not retried automatically. Never log the webhook credential.
- An independent, explicitly *estimated* quote model: buy at recorded ask, sell at recorded bid, deduct supplied per-contract fees. Missing quotes stay ungraded; independent quote records may be supplied programmatically using `record_quote`.

## Operator configuration (Render secret/environment settings)

Keep all defaults disabled until a human has verified the TradersPost subscription is attached **exclusively** to the built-in paper account. Index Options asset class, SPX ticker, and option-direction settings must match the mapping (CALL=open buy, PUT=open sell). Ensure that the TradersPost strategy does **not** subscribe to any live broker/account.

- `APEX_TRADERSPOST_MODE=paper`
- `APEX_TRADERSPOST_PAPER_CONFIRMED=true` (operator attestation, not API-verifiable)
- `APEX_TRADERSPOST_SEND_ENABLED=true` (only after configuration checks)
- `APEX_TRADERSPOST_WEBHOOK_URL=<full private TradersPost strategy webhook>`
- `APEX_TRADERSPOST_OPERATOR_TOKEN=<random 24+ character private token>`
- `APEX_TRADERSPOST_LEDGER_DB=/data/apex_traderspost_paper.sqlite3` (persistent Render volume)
- `APEX_LIVE_ORDER_ROUTING_ENABLED=false` (**do not enable in paper mode**)

POST JSON to `/api/paper/traderspost/dispatch` with `X-APEX-Paper-Token`. Required request fields: `signal_id`, `decision_id`, `governance_approved`, `human_approved`, `ticker` SPX, `action` open/exit, `option_type` call/put, `expiration` YYYY-MM-DD, `strike`, `quantity`, `bid`, `ask`. The two approvals are currently *caller assertions*, not verified against the canonical decision database: operate only from a trusted upstream service; endpoint exposure and authorization need external review. The `exit` webhook signals a strategy-level exit and is not proof that the specified strike was closed. 

GET `/api/paper/traderspost/status` reports the current switches, not account identity. **There is no API verification of the remote subscription being paper-only.**

## Explicit limits / release hold

This is a candidate implementation: no production credentials were used, no webhook was sent, and no fills were confirmed. TradersPost built-in paper fills are simplified and cannot validate actual profitability. Quote ingestion is a library interface, not yet wired into APEX's canonical quote snapshots, and no broker execution reconciliation is available. Full daily realized P&L lockout and automatic exit/position reconciliation are not implemented. Do **not** authorize unattended forwarding until canonical decision verification, quote capture, live-account exclusion validation and complete governance tests are implemented and verified.

`python -m pytest -q tests/test_apex_69_10_39_traderspost_paper.py`

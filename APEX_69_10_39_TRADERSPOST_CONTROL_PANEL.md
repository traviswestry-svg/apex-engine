# APEX 69.10.39 — TradersPost Paper Control Panel

## Deployment
Copy the changed files to the same paths in GitHub and run full CI before deploying. Open `/apex_os/traderspost` after logging in to APEX. Existing APEX global authentication guards both new GET endpoints. No operator token is requested for read-only diagnostics.

## Security and scope
- `/api/paper/traderspost/panel-summary` is GET-only and exposes sanitized configuration, fixed readiness blockers and a limited paper webhook ledger.
- Never displays webhook URL, token, raw payload, decision identifiers, or bid/ask quotes.
- The panel offers no POST, trading, credential-storage, or connectivity-test controls.
- Existing operator-token requirements for dispatch and connectivity test are unchanged.
- No fill confirmation is available; webhook delivery does not prove execution.
- The standalone browser session remains protected by `engine.auth` and ordinary login expiry.

## Limitations
The read-only panel cannot confirm TradersPost fills or independently grade positions. Full repo CI must pass in a provisioned environment before release certification.

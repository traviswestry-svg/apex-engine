# APEX 69.10.39 — Read-only operator authentication check

Patch on top of the uploaded 69.10.39 repository. No execution authority, broker routing, signal rules, release number, or configuration-variable names are changed.

## Route

`GET /api/paper/traderspost/auth-check`

Send `X-APEX-Paper-Token` matching `APEX_TRADERSPOST_OPERATOR_TOKEN` (at least 24 characters). Missing or invalid credentials return HTTP 403 with `{ "ok": false, "authorized": false }`. Valid credentials return HTTP 200 with `{ "ok": true, "authorized": true, "mode": "paper", "send_enabled": true }` (values are based on current configuration). No secret is returned. This route does not send signals or initiate orders. It does not verify TradersPost receipt, paper-account status, position state or actual fills.

The dispatch route was refactored to reuse exactly the same operator-token check, without changing its behavior.

## Test status (local sandbox)

* Existing TradersPost paper tests: 5 passed.
* New Flask endpoint tests: skipped because Flask is not installed in this sandbox. They must pass in project CI before deployment.
* Governance/release/gamma focused batch: 33 passed, 1 failed due to missing Flask import in app.py.
* Syntax compile: passed.
* Full CI was not certified in this environment. Do not promote without CI and regression checks.

## Read-only test (PowerShell after deployment)

```powershell
$token = Read-Host 'APEX operator token'
$headers = @{ 'X-APEX-Paper-Token' = $token }
Invoke-RestMethod -Method Get -Uri 'https://apex-engine-dashboard.onrender.com/api/paper/traderspost/auth-check' -Headers $headers
Remove-Variable token,headers
```

Avoid displaying or committing credentials. Never test with an authenticated POST to the dispatch route unless a paper order is explicitly intended.

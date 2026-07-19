# APEX 18.0.1 Validation Report

- Full test suite: **898 passed, 0 failed**
- New complex-order tests: **4 passed**
- Existing Trade Command tests retained: **29 passed**
- JavaScript syntax check: passed
- Python compile check: passed
- Flask application import: passed
- Registered Flask routes: **458**
- `/api/trade/spx/arm-strategy`: registered
- `/api/trade/spx/preview-strategy`: registered
- `/api/trade/spx/place-strategy`: registered
- `/apex_os/trade_command`: HTTP 200

## Tested behaviors

- Four Iron Condor legs resolve in correct buy/sell order.
- Same-day expiration reports 0 DTE.
- Missing contracts block execution.
- Missing OCC/OSI identifiers block execution.
- E*TRADE preview payload contains one order with four instruments.
- Net-credit order price type is preserved.

# APEX 43.6 — Liquidity Race Engine

## Added
- Deterministic advisory engine estimating whether upper or lower liquidity is likely to be reached first.
- Inputs include order flow, delta, momentum, structure, auction state, liquidity pressure, distance, and displayed size.
- Displayed resting size is capped at a 3% model weight because visible orders may be cancelled or spoofed.
- Fail-closed response when valid levels do not exist above and below current price.
- Live integration into `/api/institutional_os` and the Flow Intelligence dashboard panel.
- Standalone `/api/liquidity-race` GET/POST endpoint.

## Interpretation
The engine predicts which pool may be *tested first*. It does not assume the level will break. At contact, APEX must reassess absorption, replenishment, delta response, and price acceptance.

## Validation
- 9 targeted and related order-flow tests passed.
- Python compilation passed for `app.py` and the new engine.
- JavaScript syntax validation passed for `static/js/apex_os.js`.

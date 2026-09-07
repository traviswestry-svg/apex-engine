# APEX 49.2 — Gamma Flip Confidence Gate

## Root cause
A one-sided cumulative GEX curve can have no local zero crossing. The prior parser selected the local minimum absolute cumulative-gamma strike, marked it LOW confidence, and downstream consumers still promoted it as the authoritative Gamma Flip. This allowed a far-band edge such as 6900 to produce the incorrect statement that spot above the flip meant dealers were long gamma, even while the reliable regime field reported short gamma.

## Fix
- Publish `active_gamma_flip` and dashboard `zero_gamma` only for a genuine local zero crossing.
- Preserve non-crossing estimates as `gamma_flip_candidate` for diagnostics only.
- Add candidate method/confidence and explicit quality flags.
- Prevent the daily-level adapter from falling back to raw zero gamma when confidence is not HIGH.
- Make the Trade Map use the provider's dealer gamma regime as the authoritative signal.
- Treat a confirmed local gamma flip as supplemental context, not as the source of regime classification.

## Expected result for the reported case
- Gamma regime remains `short_gamma`.
- 6900 is retained only as diagnostic candidate/raw curve context.
- Gamma Flip and Zero Gamma display as unavailable when no real local crossing exists.
- Trade Map says dealer gamma is SHORT and warns of momentum/expansion risk.

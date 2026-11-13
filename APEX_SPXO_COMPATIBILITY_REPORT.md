# APEX 69.10.47 — SPXO Contract Lifecycle, Settlement Identity & Execution Preflight Compatibility Audit

**Status:** candidate, not deployed; full CI not certified. Source baseline: `apex-engine-main(20261112-221036).zip` (archive SHA/release tree from November 12). APEX release number not modified.

## Authoritative Cboe requirements (as of Nov 13, 2026)
- SPXO = **AM** weekly SPX index option; settlement reference **SET**, opening-settlement value. SPXW = PM settlement. Root SPX = standard AM monthly.
- First SPXO expiration dates: **November 18** and **December 16**, 2026.
- Expiring SPXO last trades **5 p.m. ET on preceding business day**; no expiring-contract overnight GTH after that cutoff under current rules. Proposed 9:25 a.m. expiration-day GTH is **not effective**.
- SPXO matching unit 33, price-time allocation. Cross-class complex order rules are class-specific; neither added nor enabled in this patch.
- Sources: https://www.cboe.com/insights/posts/cboe-introduces-am-settled-weekly-options-on-the-s-p-500-index/ and https://www.cboe.com/tradable_products/sp_500/spx_weekly_options/specifications

## Verified repository gaps
1. `engine/execution/broker_interface.py` OptionContract lacked contract class, settlement type/reference and trading cutoff.
2. `engine/options/options_data_bus.py` normalized all option roots to underlying symbol SPX without separate settlement metadata.
3. `engine/options/polygon_chain.py` emitted the raw option ticker as `symbol`, but did not explicitly preserve separate `contract_ticker`.
4. `engine/execution/paper_order_preflight.py` checked `ticker == SPX` but did not distinguish AM SPXO from PM SPXW.
5. `engine/execution/traderspost_paper.py` checked underlying SPX, not an explicit SPXO guard. **Important:** `dispatch()` independently always raises `PAPER_EXECUTION_AUTHORITY_NOT_VERIFIED_69_10_40`, and this patch does not lift that blocker.
6. `engine/gamma.py` applies underlying-level gamma computations. Exact contract-class segregation and source completeness for all upstream providers **remain to be audited**; this patch does not claim class-aware gamma aggregation across sources.
7. Canonical evidence persistence downstream of the normalized contract model was **not exhaustively audited** and may still omit settlement identity. Do **not** promote execution eligibility based solely on these metadata additions.

## Candidate patch
- `engine/options/spxo_contract_lifecycle.py`: strict source-root recognition, AM/PM identity, SET vs closing reference, known date-specific cutoffs, contradiction checks, `execution_blockers` (no permission path).
- `engine/execution/broker_interface.py`: optional contract identity fields appended without disrupting existing constructor positions.
- `engine/options/options_data_bus.py`: preserve metadata in OptionContract and `to_dict()` for discovery/dashboard consumers.
- `engine/options/polygon_chain.py`: explicitly retain the provider's exact contract ticker.
- `engine/execution/paper_order_preflight.py`: add fail-closed SPXO/AM/unknown-class diagnostics, never authorize orders.
- `engine/execution/trade_risk_guard.py`: reject explicitly identified SPXO/AM or contradictory/unrecognized roots; leave legacy no-OSI contracts at existing behavior to avoid unrelated strategy regression. This means **the legacy non-TradersPost risk guard does not universally fail closed when class identity is wholly absent**. Address that separately only after all legacy order producers have class fields.
- `engine/execution/traderspost_paper.py`: reject SPXO/AM/unknown contract classes in `make_signal` (existing gateway's trusted authority blocker remains unchanged).
- `scripts/spxo_compatibility_audit.py`: read-only offline audit of an operator-provided JSON array of contract records. No DB writes, outbound requests or broker calls.
- `tests/test_spxo_contract_compatibility.py`: Cboe identity, same-expiry separation, contradiction, unknowns, known cutoff, Polygon + OptionContract preservation, preflight and paper guard, audit tests.

## Test evidence
- Selected 80 tests passed (including consolidation guard, release truth, gamma stability, chain, trade-command, new SPXO tests).
- Additional 62 tests passed (canonical gamma identity, settlement, options quality and complex execution).
- Total 142 passed in separate selected suites; neither full test discovery nor full CI was certified here.
- `compileall` passed for touched engine modules. No changes to environment variables, version manifest, execution authority, settlement eligibility or database schema.

## Important release blockers and follow-up audits
- Confirm each live source adapter maps option contract **class** correctly. Provider symbol parsing alone is not sufficient if provider supplies only an underlying ticker.
- Confirm canonical evidence and gamma-input schemas persist and use class + settlement identity; no historical identity reconstruction, fuzzy joins or synthetic evidence.
- Check all contract selectors and non-TradersPost broker order-entry paths before using SPXO/AM chain rows; unsupported classes must not inherit PM 0DTE rules.
- Integration/CI must be run on **current deployed repository**, not blindly overlay this ZIP onto newer updates.
- There is no SPXO execution enablement and **no guarantee** of fully protected gamma or legacy broker dispatch across the application. Safety review remains required before any operational rollout.

## Usage
`python -m scripts.spxo_compatibility_audit contract_records.json`

Stage 3 SQLite storage optimization stays deferred.

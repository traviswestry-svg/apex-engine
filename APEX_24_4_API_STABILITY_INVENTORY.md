# APEX 24.4 — /api/multi-timeframe/* API Stability Inventory

## 1. Pre-change route inventory

No `/api/multi-timeframe/*` routes existed prior to this release
(`grep -rn "multi-timeframe" --include=*.py` returned no routes). This is a
net-new, additive namespace.

## 2. Consumers identified

None (new namespace). The existing `build_multi_timeframe_profiles` in
`institutional_market_structure_engine.py` is a separate volume-profile concern
and is untouched.

## 3. Changes and compatibility

All routes are additive. No existing endpoint changed.

## 4. Breaking changes

None.

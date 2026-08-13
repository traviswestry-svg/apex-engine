# APEX 6.3.3 Changelog — Chart Overlay System

**Sprint:** 6.3.3  
**Date:** 2026-06-28  
**Status:** Production

## Changes

### static/js/overlays.js (UPGRADED)
- Full toggle group system: gamma / volumeProfile / vwap / previousDay / openingRange
- `setToggle(group, enabled)` / `getToggle(group)` — live toggle state
- Array-valued levels support: HVN and LVN each rendered as individual price lines
- `buildLevelsFromChartPayload()` — merges gamma, volume profile, VWAP, structure from chart state
- Viewport preservation: saves and restores visible range on every overlay refresh
- Opening Range High / Low overlay support (ORH / ORL)
- Previous Day High / Low (PDH / PDL)
- raw_zero_gamma hidden by default; visible only in dev mode
- POC rendered with lineWidth 2 for emphasis; VWAP rendered solid (style 0)
- Distinct styles: dotted for HVN/LVN, dashed for most levels, solid for VWAP

### templates/apex_os.html — Overlay Toggle Panel (NEW)
- Card: "Chart Overlays" in the terminal side panel
- Five toggle buttons: Gamma / Vol Profile / VWAP / Prev Day / Opn Range
- Purple active state; gray inactive state

### static/css/apex_os.css
- `.overlay-toggles` and `.overlay-btn` styles
- `.overlay-btn.active` purple highlight

## Integration Notes
- Overlay values come from /api/charts/state backend — no levels calculated in JS
- Null/unavailable levels are skipped silently
- `applyPriceLineOverlays()` respects toggle state before rendering
- Chart iframe can call `reapplyOverlays()` to re-render when toggle changes

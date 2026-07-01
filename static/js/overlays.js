/**
 * overlays.js — APEX 6.3.3 Chart Overlay System
 *
 * Renders institutional price-level overlays on Lightweight Charts without
 * resetting chart zoom/pan.  All values come from the backend API.
 * No institutional levels are calculated here.
 *
 * Toggle groups:
 *   gamma        — Call Wall, Put Wall, Active Gamma Flip
 *   volumeProfile — POC, VAH, VAL, HVN, LVN
 *   vwap         — VWAP
 *   previousDay  — Previous Day High / Low
 *   openingRange — Opening Range High / Low
 */
(function (window) {
  'use strict';

  // ── Color palette ───────────────────────────────────────────────────────
  const COLORS = {
    call_wall:         '#22c55e',
    put_wall:          '#ef4444',
    active_gamma_flip: '#f59e0b',
    zero_gamma:        '#f59e0b',
    raw_zero_gamma:    '#64748b',
    vwap:              '#38bdf8',
    poc:               '#a78bfa',
    vah:               '#fbbf24',
    val:               '#fbbf24',
    hvn:               '#c084fc',
    lvn:               '#94a3b8',
    previous_high:     '#f97316',
    previous_low:      '#f97316',
    opening_range_high:'#0ea5e9',
    opening_range_low: '#0ea5e9',
    resistance:        '#ef4444',
    support:           '#22c55e',
  };

  const LABELS = {
    call_wall:          'Call Wall',
    put_wall:           'Put Wall',
    active_gamma_flip:  'Gamma Flip',
    zero_gamma:         'Gamma Flip',
    raw_zero_gamma:     'Raw Zero Γ (dev)',
    vwap:               'VWAP',
    poc:                'POC',
    vah:                'VAH',
    val:                'VAL',
    hvn:                'HVN',
    lvn:                'LVN',
    previous_high:      'PDH',
    previous_low:       'PDL',
    opening_range_high: 'ORH',
    opening_range_low:  'ORL',
    resistance:         'Resistance',
    support:            'Support',
  };

  // Which toggle group each key belongs to
  const OVERLAY_GROUPS = {
    call_wall:          'gamma',
    put_wall:           'gamma',
    active_gamma_flip:  'gamma',
    zero_gamma:         'gamma',
    raw_zero_gamma:     'gamma',
    vwap:               'vwap',
    poc:                'volumeProfile',
    vah:                'volumeProfile',
    val:                'volumeProfile',
    hvn:                'volumeProfile',
    lvn:                'volumeProfile',
    previous_high:      'previousDay',
    previous_low:       'previousDay',
    opening_range_high: 'openingRange',
    opening_range_low:  'openingRange',
    resistance:         'volumeProfile',
    support:            'volumeProfile',
  };

  // Default toggle states — all on
  const _toggleState = {
    gamma:        true,
    volumeProfile: true,
    vwap:         true,
    previousDay:  true,
    openingRange: true,
  };

  function setToggle(group, enabled) {
    if (group in _toggleState) {
      _toggleState[group] = !!enabled;
    }
  }

  function getToggle(group) {
    return _toggleState[group] !== false;
  }

  function finitePositive(v) {
    const n = Number(v);
    return Number.isFinite(n) && n > 0 ? n : null;
  }

  /**
   * Normalize a levels object into an array of overlay descriptors.
   *
   * Handles:
   *  - Simple scalar levels:  { poc: 7349.25, vah: 7358.5, ... }
   *  - Array levels (HVN/LVN): { hvn: [7348.5, 7352.0], lvn: [7345.25] }
   *
   * Skips keys whose toggle group is currently disabled.
   * Skips raw_zero_gamma unless includeRaw is true.
   */
  function normalizeLevels(levels, options) {
    const opts = options || {};
    const includeRaw = !!opts.includeRaw;
    const out = [];
    const src = levels || {};

    Object.keys(src).forEach(function (key) {
      if (key === 'raw_zero_gamma' && !includeRaw) return;

      const group = OVERLAY_GROUPS[key];
      if (group && !getToggle(group)) return;

      const val = src[key];

      // Array-valued keys (HVN, LVN)
      if (Array.isArray(val)) {
        val.forEach(function (price, idx) {
          const p = finitePositive(price);
          if (!p) return;
          out.push({
            key:   key + '_' + idx,
            price: p,
            title: (LABELS[key] || key.toUpperCase()) + ' ' + (idx + 1),
            color: COLORS[key] || '#94a3b8',
            lineStyle: 1,  // dotted
            lineWidth: 1,
          });
        });
        return;
      }

      const p = finitePositive(val);
      if (!p) return;

      out.push({
        key:   key,
        price: p,
        title: LABELS[key] || key.replace(/_/g, ' ').toUpperCase(),
        color: COLORS[key] || '#94a3b8',
        lineStyle: (key === 'vwap') ? 0 : 2,  // solid for VWAP, dashed otherwise
        lineWidth: (key === 'poc') ? 2 : 1,
      });
    });

    return out;
  }

  function clearPriceLines(engine) {
    if (!engine || !engine.priceLines) return;
    engine.priceLines.forEach(function (line) {
      try { engine.candleSeries.removePriceLine(line); } catch (_) {}
    });
    engine.priceLines = [];
  }

  /**
   * Apply price-line overlays to a chart engine without resetting zoom/pan.
   *
   * @param {Object} engine       - ChartEngine instance with candleSeries + priceLines.
   * @param {Object} levels       - Key→value or Key→array level map from the backend.
   * @param {Object} [options]    - { includeRaw: bool }
   */
  function applyPriceLineOverlays(engine, levels, options) {
    if (!engine || !engine.candleSeries) return;
    // basisOffset: passed from chart.html for any remaining client-side adjustment.
    // For ES, levels are pre-shifted server-side so this is 0. Kept for safety.
    const basis = Number((options || {}).basisOffset || 0);

    let savedRange = null;
    try {
      if (engine.chart && engine.chart.timeScale) {
        savedRange = engine.chart.timeScale().getVisibleRange();
      }
    } catch (_) {}

    clearPriceLines(engine);
    const normalized = normalizeLevels(levels, options);

    normalized.forEach(function (level) {
      try {
        const adjustedPrice = level.price + basis;
        const line = engine.candleSeries.createPriceLine({
          price:            adjustedPrice,
          color:            level.color,
          lineWidth:        level.lineWidth || 1,
          lineStyle:        level.lineStyle != null ? level.lineStyle : 2,
          axisLabelVisible: true,
          title:            level.title + ' ' + adjustedPrice.toFixed(2),
        });
        engine.priceLines.push(line);
      } catch (_) {}
    });

    if (savedRange) {
      try { engine.chart.timeScale().setVisibleRange(savedRange); } catch (_) {}
    }
  }

  /**
   * Build the standard levels object from a /api/charts/state chart payload.
   * Merges gamma levels, volume profile levels, VWAP, and structure levels.
   */
  function buildLevelsFromChartPayload(chartPayload, options) {
    const opts      = options || {};
    const devMode   = !!opts.devMode;
    const vp        = (chartPayload.volumeProfile || {}).levels || {};
    const lvl       = chartPayload.levels || {};
    const structure = chartPayload.structure || {};

    return Object.assign({}, lvl, {
      // Volume Profile
      poc:               vp.poc  || lvl.poc,
      vah:               vp.vah  || lvl.vah,
      val:               vp.val  || lvl.val,
      hvn:               vp.hvn  || [],
      lvn:               vp.lvn  || [],
      // Structure
      vwap:              structure.vwap || lvl.vwap,
      previous_high:     structure.previous_high || lvl.previous_high,
      previous_low:      structure.previous_low  || lvl.previous_low,
      opening_range_high: structure.opening_range_high || lvl.opening_range_high,
      opening_range_low:  structure.opening_range_low  || lvl.opening_range_low,
      // Raw zero-gamma only in dev mode
      raw_zero_gamma:    devMode ? lvl.raw_zero_gamma : undefined,
    });
  }

  window.APEXOverlays = {
    applyPriceLineOverlays,
    clearPriceLines,
    normalizeLevels,
    buildLevelsFromChartPayload,
    setToggle,
    getToggle,
    COLORS,
    LABELS,
    OVERLAY_GROUPS,
  };

})(window);

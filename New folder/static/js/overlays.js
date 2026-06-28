(function (window) {
  'use strict';

  const DEFAULT_COLORS = {
    call_wall: '#22c55e',
    put_wall: '#ef4444',
    active_gamma_flip: '#f59e0b',
    zero_gamma: '#f59e0b',
    raw_zero_gamma: '#64748b',
    vwap: '#38bdf8',
    poc: '#a78bfa',
    hvbo_low: '#a78bfa',
    hvbo_high: '#a78bfa',
    previous_high: '#f97316',
    previous_low: '#f97316',
    resistance: '#ef4444',
    support: '#22c55e'
  };

  const DEFAULT_LABELS = {
    call_wall: 'Call Wall',
    put_wall: 'Put Wall',
    active_gamma_flip: 'Gamma Flip',
    zero_gamma: 'Gamma Flip',
    raw_zero_gamma: 'Raw Zero Γ',
    vwap: 'VWAP',
    poc: 'POC',
    hvbo_low: 'HVBO Low',
    hvbo_high: 'HVBO High',
    previous_high: 'PDH',
    previous_low: 'PDL',
    resistance: 'Resistance',
    support: 'Support'
  };

  function finiteNumber(value) {
    const n = Number(value);
    return Number.isFinite(n) && n > 0 ? n : null;
  }

  function normalizeLevels(levels, options) {
    const opts = options || {};
    const includeRaw = !!opts.includeRaw;
    const out = [];
    const src = levels || {};
    Object.keys(src).forEach((key) => {
      if (key === 'raw_zero_gamma' && !includeRaw) return;
      const price = finiteNumber(src[key]);
      if (!price) return;
      out.push({
        key,
        price,
        title: DEFAULT_LABELS[key] || key.replace(/_/g, ' ').toUpperCase(),
        color: DEFAULT_COLORS[key] || '#94a3b8'
      });
    });
    return out;
  }

  function clearPriceLines(engine) {
    if (!engine || !engine.priceLines) return;
    engine.priceLines.forEach((line) => {
      try { engine.candleSeries.removePriceLine(line); } catch (_) {}
    });
    engine.priceLines = [];
  }

  function applyPriceLineOverlays(engine, levels, options) {
    if (!engine || !engine.candleSeries) return;
    clearPriceLines(engine);
    const normalized = normalizeLevels(levels, options);
    normalized.forEach((level) => {
      try {
        const line = engine.candleSeries.createPriceLine({
          price: level.price,
          color: level.color,
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: `${level.title} ${level.price.toFixed(2)}`
        });
        engine.priceLines.push(line);
      } catch (_) {}
    });
  }

  window.APEXOverlays = {
    applyPriceLineOverlays,
    clearPriceLines,
    normalizeLevels
  };
})(window);

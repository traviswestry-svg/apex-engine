(function (window) {
  'use strict';

  const store = new Map();

  function save(chartId, chart) {
    if (!chart || !chart.timeScale) return;
    try {
      const range = chart.timeScale().getVisibleLogicalRange();
      if (range) store.set(chartId, range);
    } catch (_) {}
  }

  function restore(chartId, chart) {
    if (!chart || !chart.timeScale) return false;
    const range = store.get(chartId);
    if (!range) return false;
    try {
      chart.timeScale().setVisibleLogicalRange(range);
      return true;
    } catch (_) {
      return false;
    }
  }

  function fitLatest(chart, barsBack) {
    if (!chart || !chart.timeScale) return;
    const count = Math.max(30, Number(barsBack || 120));
    try {
      chart.timeScale().scrollToRealTime();
      const range = chart.timeScale().getVisibleLogicalRange();
      if (range && Number.isFinite(range.to)) {
        chart.timeScale().setVisibleLogicalRange({ from: range.to - count, to: range.to + 5 });
      }
    } catch (_) {}
  }

  function fitAll(chart) {
    if (!chart || !chart.timeScale) return;
    try { chart.timeScale().fitContent(); } catch (_) {}
  }

  window.APEXViewport = { save, restore, fitLatest, fitAll };
})(window);

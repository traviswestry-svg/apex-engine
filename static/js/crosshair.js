(function (window) {
  'use strict';

  function bindCrosshair(engine, outputEl) {
    if (!engine || !engine.chart || !outputEl) return;
    engine.chart.subscribeCrosshairMove((param) => {
      if (!param || !param.time || !param.seriesData) {
        outputEl.innerHTML = '<span class="muted">Hover a candle</span>';
        return;
      }
      const data = param.seriesData.get(engine.candleSeries);
      if (!data) return;
      const time = typeof param.time === 'object' ? JSON.stringify(param.time) : param.time;
      outputEl.innerHTML = `
        <span>${engine.symbol}</span>
        <span>T ${time}</span>
        <span>O ${num(data.open)}</span>
        <span>H ${num(data.high)}</span>
        <span>L ${num(data.low)}</span>
        <span>C ${num(data.close)}</span>
      `;
    });
  }

  function num(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n.toFixed(2) : '--';
  }

  window.APEXCrosshair = { bindCrosshair };
})(window);

(function (window) {
  'use strict';

  function addCandles(chart) {
    if (chart.addCandlestickSeries) return chart.addCandlestickSeries({
      upColor: '#22c55e', downColor: '#ef4444', borderVisible: false,
      wickUpColor: '#22c55e', wickDownColor: '#ef4444', priceLineVisible: false
    });
    return chart.addSeries(LightweightCharts.CandlestickSeries, {
      upColor: '#22c55e', downColor: '#ef4444', borderVisible: false,
      wickUpColor: '#22c55e', wickDownColor: '#ef4444', priceLineVisible: false
    });
  }

  function addLine(chart, color, width) {
    if (chart.addLineSeries) return chart.addLineSeries({ color, lineWidth: width || 1, priceLineVisible: false, lastValueVisible: false });
    return chart.addSeries(LightweightCharts.LineSeries, { color, lineWidth: width || 1, priceLineVisible: false, lastValueVisible: false });
  }

  function toSeriesCandles(candles) {
    return (candles || []).filter(Boolean).map((c) => ({
      time: Number(c.ts_et || Math.floor(Number(c.ts || 0) / 1000)),
      open: Number(c.open), high: Number(c.high), low: Number(c.low), close: Number(c.close)
    })).filter((c) => c.time && [c.open, c.high, c.low, c.close].every(Number.isFinite));
  }

  function toLine(candles, key) {
    return (candles || []).map((c) => {
      const value = Number(c[key]);
      const time = Number(c.ts_et || Math.floor(Number(c.ts || 0) / 1000));
      return Number.isFinite(value) && value > 0 && time ? { time, value } : null;
    }).filter(Boolean);
  }

  class ApexChartEngine {
    constructor(containerId, options) {
      this.container = document.getElementById(containerId);
      this.options = options || {};
      this.symbol = this.options.symbol || containerId;
      this.priceLines = [];
      this.lastPayload = null;
      this.chart = null;
      this.candleSeries = null;
      this.ema8Series = null;
      this.ema21Series = null;
      this.vwapSeries = null;
      this.init();
    }

    init() {
      if (!this.container || !window.LightweightCharts) return;
      const rect = this.container.getBoundingClientRect();
      this.chart = LightweightCharts.createChart(this.container, {
        width: Math.max(300, rect.width || this.container.clientWidth),
        height: Math.max(320, rect.height || 460),
        layout: { background: { type: 'solid', color: '#05080f' }, textColor: '#94a3b8', fontFamily: 'Inter, system-ui, sans-serif' },
        grid: { vertLines: { color: 'rgba(148,163,184,0.08)' }, horzLines: { color: 'rgba(148,163,184,0.08)' } },
        rightPriceScale: { borderColor: '#1e293b', autoScale: true, scaleMargins: { top: 0.12, bottom: 0.12 } },
        timeScale: { borderColor: '#1e293b', timeVisible: true, secondsVisible: false, rightOffset: 8, barSpacing: 8, fixLeftEdge: false, fixRightEdge: false, lockVisibleTimeRangeOnResize: true, rightBarStaysOnScroll: true },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
        handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true }
      });
      this.candleSeries = addCandles(this.chart);
      this.ema8Series = addLine(this.chart, '#38bdf8', 1);
      this.ema21Series = addLine(this.chart, '#a78bfa', 1);
      this.vwapSeries = addLine(this.chart, '#f59e0b', 1);
    }

    setData(payload) {
      if (!payload || !this.chart) return;
      if (window.APEXViewport) window.APEXViewport.save(this.container.id, this.chart);
      this.lastPayload = payload;
      this.symbol = payload.symbol || this.symbol;
      const candles = payload.candles || [];
      const seriesCandles = toSeriesCandles(candles);
      this.candleSeries.setData(seriesCandles);
      this.ema8Series.setData(toLine(candles, 'ema8'));
      this.ema21Series.setData(toLine(candles, 'ema21'));
      this.vwapSeries.setData(toLine(candles, 'vwap'));
      if (window.APEXOverlays) window.APEXOverlays.applyPriceLineOverlays(this, payload.levels || {}, { includeRaw: !!payload.includeRawZeroGamma });
      const restored = window.APEXViewport && window.APEXViewport.restore(this.container.id, this.chart);
      if (!restored) this.fitLatest();
    }

    updateLast(payload) {
      this.setData(payload);
    }

    fitLatest() {
      if (window.APEXViewport) window.APEXViewport.fitLatest(this.chart, 120);
    }

    fitAll() {
      if (window.APEXViewport) window.APEXViewport.fitAll(this.chart);
    }

    reset() { this.fitLatest(); }

    resize() {
      if (!this.chart || !this.container) return;
      const rect = this.container.getBoundingClientRect();
      this.chart.applyOptions({ width: Math.max(300, rect.width), height: Math.max(320, rect.height) });
    }
  }

  window.ApexChartEngine = ApexChartEngine;
})(window);

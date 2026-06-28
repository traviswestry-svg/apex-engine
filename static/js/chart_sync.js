(function (window) {
  'use strict';

  class ChartSynchronizer {
    constructor() {
      this.engines = [];
      this.locked = false;
    }

    add(engine) {
      if (!engine || !engine.chart || !engine.chart.timeScale) return;
      this.engines.push(engine);
      engine.chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (!range || this.locked) return;
        this.locked = true;
        this.engines.forEach((other) => {
          if (other === engine || !other.chart) return;
          try { other.chart.timeScale().setVisibleLogicalRange(range); } catch (_) {}
        });
        window.setTimeout(() => { this.locked = false; }, 0);
      });
    }

    fitAll() { this.engines.forEach((e) => e.fitAll()); }
    fitLatest() { this.engines.forEach((e) => e.fitLatest()); }
    resize() { this.engines.forEach((e) => e.resize()); }
  }

  window.APEXChartSynchronizer = ChartSynchronizer;
})(window);

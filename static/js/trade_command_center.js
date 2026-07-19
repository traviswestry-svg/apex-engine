/* trade_command_center.js — APEX SPX Trade Command Center
 * Dual synced panes: SPX price (I:SPX cash) + modeled option premium.
 * Six linked, draggable trade lines: Entry / Stop / Breakeven / TP1 / TP2 / TP3.
 * Dragging in either pane moves the twin in the other via the SPX<->premium mapper;
 * the server (/api/trade/spx/project-levels) is the source of truth on release.
 * Built on Lightweight Charts v5 (same standalone build as /chart). SPX only, no ES.
 */
(function () {
  "use strict";

  const LWC = window.LightweightCharts;
  const $ = (id) => document.getElementById(id);

  const LINE_DEFS = [
    { tag: "ENTRY",     label: "Entry", color: "#38bdf8" },
    { tag: "STOP",      label: "Stop",  color: "#ef4444" },
    { tag: "BREAKEVEN", label: "B/E",   color: "#8a94a3" },
    { tag: "TP1",       label: "TP1",   color: "#22c55e" },
    { tag: "TP2",       label: "TP2",   color: "#10b981" },
    { tag: "TP3",       label: "TP3",   color: "#14b8a6" },
  ];
  const HIT_PX = 7;              // how close the cursor must be to grab a line
  const SPX_TICK = 0.25;

  const state = {
    spot: null, basePremium: null, delta: null, gamma: 0, qty: 1,
    mode: "planning", filled: false, fillPremium: null,
    contractLabel: "— no contract —",
    lines: {},                   // tag -> { prem, spx }
    candles: [],
    spxPane: null, premPane: null,
    drag: null, syncing: false, armed: false,
    days: 1, tf: 5, side: "CALL",
  };

  // ── mapper mirror (instant feedback; server reconciles on release) ──────────
  const snap = (v, tick) => Math.round(v / tick) * tick;
  const premTick = (p) => (p <= 3 ? 0.05 : 0.10);
  const snapPrem = (p) => Math.max(0, +(snap(p, premTick(p))).toFixed(2));
  const snapSpx = (s) => +(snap(s, SPX_TICK)).toFixed(2);

  function premiumFromSpx(spxLevel) {
    const { spot, basePremium, delta } = state;
    return snapPrem(basePremium + delta * (spxLevel - spot));
  }
  function spxFromPremium(prem) {
    const { spot, basePremium, delta } = state;
    if (Math.abs(delta) < 1e-4) return null;
    return snapSpx(spot + (prem - basePremium) / delta);
  }

  // ── chart setup ─────────────────────────────────────────────────────────────
  function makeChart(el, isPremium) {
    const axis = isPremium ? "prem" : "spx";
    const chart = LWC.createChart(el, {
      layout: { background: { color: "transparent" }, textColor: "#8a94a3", fontFamily: "JetBrains Mono, monospace" },
      grid: { vertLines: { color: "rgba(35,45,63,0.5)" }, horzLines: { color: "rgba(35,45,63,0.5)" } },
      rightPriceScale: { borderColor: "#232d3f" },
      timeScale: { borderColor: "#232d3f", timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
      handleScroll: true, handleScale: true,
      autoSize: true,
    });
    let series;
    if (isPremium) {
      series = chart.addSeries(LWC.LineSeries, { color: "#38bdf8", lineWidth: 2, priceLineVisible: false });
    } else {
      series = chart.addSeries(LWC.CandlestickSeries, {
        upColor: "#22c55e", downColor: "#ef4444", borderVisible: false,
        wickUpColor: "#22c55e", wickDownColor: "#ef4444",
      });
    }
    // invisible flat guide series at the min & max trade-line prices. Because they
    // carry a point at EVERY visible bar, the pane's autoscale (which only considers
    // data inside the visible time window) is always forced to include the lines.
    const mkGuide = () => chart.addSeries(LWC.LineSeries, {
      color: "rgba(0,0,0,0)", lineWidth: 1, priceLineVisible: false,
      lastValueVisible: false, crosshairMarkerVisible: false, pointMarkersVisible: false,
    });
    const guideHi = mkGuide(), guideLo = mkGuide();
    return { chart, series, guideHi, guideLo, el, priceLines: {} };
  }

  function initCharts() {
    state.spxPane = makeChart($("tccSpxChart"), false);
    state.premPane = makeChart($("tccPremChart"), true);
    // keep the two time axes locked together (guarded against feedback)
    const link = (from, to) => from.chart.timeScale().subscribeVisibleLogicalRangeChange((r) => {
      if (state.syncing || !r) return;
      state.syncing = true;
      try { to.chart.timeScale().setVisibleLogicalRange(r); } catch (e) {}
      state.syncing = false;
    });
    link(state.spxPane, state.premPane);
    link(state.premPane, state.spxPane);
    attachDrag(state.spxPane, "spx");
    attachDrag(state.premPane, "prem");
  }

  function fitAll() {
    try { state.spxPane.chart.timeScale().fitContent(); } catch (e) {}
    try { state.premPane.chart.timeScale().fitContent(); } catch (e) {}
  }

  // ── data ─────────────────────────────────────────────────────────────────────
  async function loadCandles() {
    log("loading SPX candles… (" + state.days + "D · " + state.tf + "m)");
    try {
      const r = await fetch("/api/trade/spx/candles?days=" + state.days + "&tf=" + state.tf);
      const j = await r.json();
      const c = (j.data && j.data.candles) || [];
      if (!c.length) { log("no SPX candles (market closed or no key) — using inputs only"); return; }
      state.candles = c;
      state.spxPane.series.setData(c.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
      if (state.spot == null && j.data.last) { state.spot = j.data.last; $("tccSpot").value = j.data.last; }
      renderPremiumSeries();
      if (state.armed) refreshLines();     // keep the trade lines after a reload
      fitAll();
      const sess = (j.data.sessions || []).length;
      log("SPX candles: " + c.length + " bars, " + (sess || "?") + " session(s), last " + j.data.last);
    } catch (e) { log("candle load error: " + e); }
  }

  // timeframe / lookback / zoom controls -------------------------------------------
  function setTf(tf) { state.tf = tf; markActive("tccTf", tf); loadCandles(); }
  function setLookback(days) { state.days = days; markActive("tccLb", days); loadCandles(); }
  function markActive(group, val) {
    document.querySelectorAll("[data-" + group + "]").forEach((b) => {
      b.classList.toggle("on", b.getAttribute("data-" + group) === String(val));
    });
  }
  function zoom(factor) {
    // narrow (<1) or widen (>1) the visible range around its center on both panes
    [state.spxPane, state.premPane].forEach((pane) => {
      if (!pane) return;
      try {
        const ts = pane.chart.timeScale();
        const r = ts.getVisibleLogicalRange();
        if (!r) return;
        const center = (r.from + r.to) / 2;
        const half = ((r.to - r.from) / 2) * factor;
        ts.setVisibleLogicalRange({ from: center - half, to: center + half });
      } catch (e) {}
    });
  }

  function renderPremiumSeries() {
    if (!state.candles.length || state.basePremium == null || state.delta == null || state.spot == null) return;
    const data = state.candles.map((b) => ({
      time: b.time,
      value: Math.max(0, +(state.basePremium + state.delta * (b.close - state.spot)).toFixed(2)),
    }));
    state.premPane.series.setData(data);
    state.premPane.chart.timeScale().fitContent();
  }

  // ── trade lines ───────────────────────────────────────────────────────────────
  function setLine(tag, prem, spx) {
    state.lines[tag] = { prem: prem, spx: (spx == null ? spxFromPremium(prem) : spx) };
  }

  function refreshLines() {
    LINE_DEFS.forEach((d) => {
      const lvl = state.lines[d.tag];
      if (!lvl) return;
      drawLine(state.spxPane, d, lvl.spx);
      drawLine(state.premPane, d, lvl.prem);
    });
    updateAnchors();
    renderCommandCenter();
  }

  // flat guide series force each pane's price range to include all trade lines
  function updateAnchors() {
    if (!state.candles.length) return;
    const times = state.candles.map((b) => b.time);
    [["spx", state.spxPane], ["prem", state.premPane]].forEach(([axis, pane]) => {
      if (!pane || !pane.guideHi) return;
      const prices = LINE_DEFS.map((d) => state.lines[d.tag] && state.lines[d.tag][axis])
        .filter((v) => v != null && isFinite(v));
      if (!prices.length) { pane.guideHi.setData([]); pane.guideLo.setData([]); return; }
      let lo = Math.min(...prices), hi = Math.max(...prices);
      const pad = (hi - lo) * 0.1 || 0.5;
      pane.guideHi.setData(times.map((t) => ({ time: t, value: hi + pad })));
      pane.guideLo.setData(times.map((t) => ({ time: t, value: Math.max(0, lo - pad) })));
    });
  }

  // re-setting series data forces Lightweight Charts to recompute the price axis,
  // which re-invokes the autoscale provider so off-screen lines pull into view.
  function rescale() {
    if (state.candles.length) {
      state.spxPane.series.setData(state.candles.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
      renderPremiumSeries();
    }
  }

  function drawLine(pane, def, price) {
    if (price == null) return;
    const existing = pane.priceLines[def.tag];
    const opts = {
      price: price, color: def.color, lineWidth: def.tag === "ENTRY" ? 2 : 1,
      lineStyle: def.tag === "BREAKEVEN" ? 2 : 0, axisLabelVisible: true, title: def.label,
    };
    if (existing) { existing.applyOptions(opts); }
    else { pane.priceLines[def.tag] = pane.series.createPriceLine(opts); }
  }

  // ── dragging ───────────────────────────────────────────────────────────────────
  function attachDrag(pane, axis) {
    const el = pane.el;
    const yOf = (evt) => evt.clientY - el.getBoundingClientRect().top;

    el.addEventListener("mousedown", (evt) => {
      const y = yOf(evt);
      let best = null, bestDist = HIT_PX + 1;
      LINE_DEFS.forEach((d) => {
        const lvl = state.lines[d.tag];
        if (!lvl) return;
        if (d.tag === "ENTRY" && state.filled) return;          // entry locks after fill
        const price = axis === "spx" ? lvl.spx : lvl.prem;
        const coord = pane.series.priceToCoordinate(price);
        if (coord == null) return;
        const dist = Math.abs(coord - y);
        if (dist < bestDist) { bestDist = dist; best = d.tag; }
      });
      if (!best) return;
      state.drag = { tag: best, axis, pane, prev: { ...state.lines[best] } };
      pane.chart.applyOptions({ handleScroll: false, handleScale: false });
      el.style.cursor = "ns-resize";
      evt.preventDefault();
    });

    window.addEventListener("mousemove", (evt) => {
      if (!state.drag || state.drag.pane !== pane) return;
      const y = yOf(evt);
      const raw = pane.series.coordinateToPrice(y);
      if (raw == null) return;
      const tag = state.drag.tag;
      if (axis === "spx") {
        const spx = snapSpx(raw);
        setLine(tag, premiumFromSpx(spx), spx);
      } else {
        const prem = snapPrem(raw);
        setLine(tag, prem, null);
      }
      refreshLines();
    });

    window.addEventListener("mouseup", async () => {
      if (!state.drag || state.drag.pane !== pane) return;
      const tag = state.drag.tag;
      pane.chart.applyOptions({ handleScroll: true, handleScale: true });
      el.style.cursor = "default";
      const drag = state.drag; state.drag = null;

      const check = validateLine(tag);
      if (!check.ok) {
        state.lines[tag] = drag.prev;             // revert illegal drag
        refreshLines();
        log("✗ " + tag + " drag rejected: " + check.reason);
        return;
      }
      await reconcileWithServer();                 // authoritative snap from server
      if (state.mode === "active" && tag !== "ENTRY") openChangeModal(tag);
      else log(tag + " → SPX " + fmt(state.lines[tag].spx) + " / $" + fmt(state.lines[tag].prem));
    });
  }

  // client mirror of the server risk rules (premium terms, long option)
  function validateLine(tag) {
    const L = state.lines, entry = L.ENTRY && L.ENTRY.prem;
    if (entry == null) return { ok: true };
    if (tag === "STOP") {
      if (L.STOP.prem >= entry) return { ok: false, reason: "stop must be below entry" };
      if (L.TP1 && L.STOP.prem >= L.TP1.prem) return { ok: false, reason: "stop above TP1" };
    }
    if (tag === "TP1" || tag === "TP2" || tag === "TP3") {
      if (L[tag].prem <= entry) return { ok: false, reason: tag + " must be above entry" };
      if (tag === "TP2" && L.TP1 && L.TP2.prem <= L.TP1.prem) return { ok: false, reason: "TP2 below TP1" };
      if (tag === "TP3" && L.TP2 && L.TP3.prem <= L.TP2.prem) return { ok: false, reason: "TP3 below TP2" };
      if (tag === "TP1" && L.TP2 && L.TP1.prem >= L.TP2.prem) return { ok: false, reason: "TP1 above TP2" };
    }
    return { ok: true };
  }

  async function reconcileWithServer() {
    if (state.spot == null || state.basePremium == null || state.delta == null) return;
    const levels = {}; Object.keys(state.lines).forEach((t) => (levels[t] = state.lines[t].prem));
    try {
      const r = await fetch("/api/trade/spx/project-levels", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spot: state.spot, base_premium: state.basePremium, delta: state.delta,
          gamma: state.gamma, source_axis: "premium", levels }),
      });
      const j = await r.json();
      const proj = j.data && j.data.projected;
      if (proj) { Object.keys(proj).forEach((t) => { if (state.lines[t]) state.lines[t] = { prem: proj[t].premium, spx: proj[t].spx }; }); refreshLines(); rescale(); }
    } catch (e) { /* local values already applied */ }
  }

  // ── command center panel ─────────────────────────────────────────────────────
  function renderCommandCenter() {
    const L = state.lines;
    $("ccContract").textContent = state.contractLabel;
    $("ccSpot").textContent = state.spot == null ? "—" : fmt(state.spot);
    $("ccDelta").textContent = state.delta == null ? "—" : fmt(state.delta);
    $("ccQty").textContent = state.qty;
    const curPrem = curPremium();
    $("ccPremium").textContent = curPrem == null ? "—" : "$" + fmt(curPrem);

    const rows = LINE_DEFS.map((d) => {
      const lvl = L[d.tag]; if (!lvl) return "";
      const dollars = (L.ENTRY ? (lvl.prem - L.ENTRY.prem) * 100 * state.qty : 0);
      return `<tr><td><span class="dot" style="background:${d.color}"></span>${d.label}</td>
        <td>${fmt(lvl.spx)}</td><td>$${fmt(lvl.prem)}</td>
        <td class="${dollars >= 0 ? "pos" : "neg"}">${dollars >= 0 ? "+" : ""}${money(dollars)}</td></tr>`;
    }).join("");
    $("ccLevels").innerHTML = rows;

    if (L.ENTRY && L.STOP && L.TP1) {
      const risk = (L.ENTRY.prem - L.STOP.prem) * 100 * state.qty;
      const reward = (L.TP1.prem - L.ENTRY.prem) * 100 * state.qty;
      const rr = risk > 0 ? (reward / risk) : 0;
      $("ccRisk").textContent = money(risk);
      $("ccRR").textContent = rr ? rr.toFixed(2) + "R" : "—";
      const pl = (state.filled && state.fillPremium != null && curPrem != null)
        ? (curPrem - state.fillPremium) * 100 * state.qty : 0;
      $("ccPL").textContent = (pl >= 0 ? "+" : "") + money(pl);
      $("ccPL").className = "cc-val " + (pl >= 0 ? "pos" : "neg");
    }
    $("ccMode").textContent = state.mode === "active" ? "ACTIVE TRADE" : "PLANNING";
    $("ccMode").className = "cc-chip " + (state.mode === "active" ? "chip-active" : "chip-plan");
  }

  function curPremium() {
    if (state.candles.length && state.delta != null && state.spot != null && state.basePremium != null) {
      const lastClose = state.candles[state.candles.length - 1].close;
      return Math.max(0, +(state.basePremium + state.delta * (lastClose - state.spot)).toFixed(2));
    }
    return state.basePremium;
  }

  // ── controls ──────────────────────────────────────────────────────────────────
  async function armPlan() {
    const rec = window.apexPremiumRecommendation || null;
    if (rec && rec.strategy && rec.strategy !== "NO_TRADE") {
      const expEl = document.getElementById("expSelect");
      const expiration = expEl && expEl.value;
      if (!expiration) { log("pick the recommended expiration before arming the strategy"); return; }
      const qty = Math.max(1, parseInt($("tccQty").value || "1", 10));
      log("resolving all contracts for " + (rec.strategy_label || rec.strategy) + "…");
      try {
        const r = await fetch("/api/trade/spx/arm-strategy", {method:"POST", headers:{"Content-Type":"application/json"},
          body:JSON.stringify({recommendation:rec, expiration, quantity:qty})});
        const j = await r.json();
        state.complexTicket = j.data || null; state.complexPreviewId = null;
        renderComplexTicket(j);
        if (state.complexTicket) { state.armed = true; log((j.ok ? "strategy armed — ready for broker preview" : "strategy populated — execution blocked until all legs validate")); }
        return;
      } catch (e) { log("strategy arm failed: " + e); return; }
    }
    const spot = parseFloat($("tccSpot").value);
    const prem = parseFloat($("tccPrem").value);
    const delta = parseFloat($("tccDelta").value);
    const qty = parseInt($("tccQty").value, 10);
    if (!spot || !prem || !delta) { log("enter spot, premium and delta to arm a plan"); return; }
    state.spot = spot; state.basePremium = prem; state.delta = delta; state.qty = qty || 1;
    renderPremiumSeries();
    try {
      const r = await fetch("/api/trade/spx/project-levels", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spot, base_premium: prem, delta, gamma: state.gamma, suggest: true }),
      });
      const j = await r.json();
      const s = j.data && j.data.suggested;
      if (s) { Object.keys(s).forEach((t) => (state.lines[t] = { prem: s[t].premium, spx: s[t].spx })); }
    } catch (e) {
      // local fallback
      setLine("ENTRY", prem); setLine("BREAKEVEN", prem);
      setLine("STOP", snapPrem(prem * 0.73));
      setLine("TP1", snapPrem(prem * 1.25)); setLine("TP2", snapPrem(prem * 1.60)); setLine("TP3", snapPrem(prem * 2.0));
    }
    state.armed = true;
    refreshLines();
    rescale();
    fitAll();
    log("plan armed — drag any line on either pane");
  }

  function toggleMode() {
    if (!state.armed) { log("arm a plan first"); return; }
    if (state.mode === "planning") {
      state.mode = "active"; state.filled = true; state.fillPremium = state.lines.ENTRY.prem;
      log("ACTIVE — entry locked at $" + fmt(state.fillPremium) + " (sandbox; no live order sent)");
    } else {
      state.mode = "planning"; state.filled = false; state.fillPremium = null;
      log("back to PLANNING — entry unlocked");
    }
    renderCommandCenter();
  }

  // ── change-preview modal (Active mode) ─────────────────────────────────────────
  async function openChangeModal(tag) {
    const lvl = state.lines[tag];
    const m = $("tccModal");
    $("tccModalConfirm").style.display = "";
    $("tccModalTitle").textContent = "Preview Change — " + tag + " (Sandbox)";
    $("tccModalBody").innerHTML =
      `<div class="mrow"><span>Contract</span><b>${state.contractLabel}</b></div>
       <div class="mrow"><span>Line</span><b>${tag}</b></div>
       <div class="mrow"><span>New SPX level</span><b>${fmt(lvl.spx)}</b></div>
       <div class="mrow"><span>New premium</span><b>$${fmt(lvl.prem)}</b></div>
       <div class="mrow"><span>Qty</span><b>${state.qty}</b></div>
       <div class="mnote">Checking APEX risk rules…</div>`;
    m.style.display = "flex";
    try {
      const r = await fetch("/api/trade/spx/preview-change", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ line: tag, new_price: lvl.prem, entry_premium: state.lines.ENTRY.prem,
          current_premium: curPremium(), side: state.side, position_qty: state.qty,
          levels: mapPrem(), breakeven_armed: false }),
      });
      const j = await r.json();
      const risk = (j.data && j.data.risk) || {};
      const okTxt = j.ok ? `<span class="pos">APEX: approved</span>` : `<span class="neg">APEX: rejected — ${(j.errors||[]).join("; ")}</span>`;
      $("tccModalBody").querySelector(".mnote").outerHTML = `<div class="mnote">${okTxt}</div>`;
    } catch (e) {
      $("tccModalBody").querySelector(".mnote").outerHTML = `<div class="mnote neg">risk check failed: ${e}</div>`;
    }
  }
  function mapPrem() { const o = {}; Object.keys(state.lines).forEach((t) => (o[t] = state.lines[t].prem)); return o; }
  function closeModal() { $("tccModal").style.display = "none"; }

  function renderComplexTicket(j) {
    const box = $("complexTicket"); if (!box) return; box.style.display = "block";
    const t = (j && j.data) || state.complexTicket || {}; const intent=t.intent||{}; const legs=intent.legs||[];
    $("complexState").textContent = (t.state||"BLOCKED").replaceAll("_"," ");
    $("complexState").className = "cc-chip " + (t.ready_for_preview ? "chip-active" : "chip-plan");
    $("complexSummary").innerHTML = `<div><span>Strategy</span><b>${t.strategy_label||intent.strategy||"—"}</b></div>`+
      `<div><span>Order</span><b>${intent.price_effect||"—"}</b></div><div><span>Expiration</span><b>${t.expiration||"—"}</b></div>`+
      `<div><span>DTE</span><b>${t.dte==null?"—":t.dte}</b></div>`;
    $("complexLegs").innerHTML = legs.map((x,i)=>`<tr><td>${i+1}</td><td><b>${x.action.replace("_"," TO ")}</b></td>`+
      `<td>${x.side} ${x.strike}<br><small>${x.osi_key||"UNRESOLVED"}</small></td><td>${x.expiration}<br>${t.dte==null?"—":t.dte+" DTE"}</td>`+
      `<td>${x.bid==null?"—":x.bid} / ${x.ask==null?"—":x.ask}</td><td>${x.mid==null?"—":x.mid}</td></tr>`).join("");
    const e=t.economics||{}; $("complexEconomics").innerHTML = `<div><b>Recommended limit:</b> $${t.recommended_limit||"—"}</div>`+
      `<div><b>Max profit:</b> ${e.max_profit==null?"—":money(e.max_profit)}</div><div><b>Max loss:</b> ${e.max_loss==null?"—":money(e.max_loss)}</div>`+
      `<div><b>Breakeven:</b> ${(e.breakevens||[]).join(" / ")||"—"}</div>`;
    $("complexLimit").value=t.recommended_limit||""; $("complexQty").value=intent.quantity||1;
    const errs=(t.errors||j.errors||[]); $("complexErrors").innerHTML=errs.length?`<span class="neg">${errs.join("<br>")}</span>`:`<span class="pos">All contracts resolved and validated.</span>`;
    $("complexPreview").disabled=!t.ready_for_preview; $("complexSubmit").disabled=true;
  }

  async function previewComplexStrategy() {
    const t=state.complexTicket; if(!t){log("arm a strategy first");return;}
    t.intent.limit_price=parseFloat($("complexLimit").value||t.recommended_limit); t.intent.quantity=parseInt($("complexQty").value||"1",10);
    t.intent.legs.forEach(x=>x.quantity=t.intent.quantity);
    try { const r=await fetch("/api/trade/spx/preview-strategy",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(t)});
      const j=await r.json(); state.complexPreviewId=j.data&&j.data.preview_id;
      const m=$("tccModal"); $("tccModalTitle").textContent="E*TRADE Strategy Preview";
      $("tccModalBody").innerHTML=j.ok?`<div class="mnote pos">✓ Broker preview approved.</div><div class="mrow"><span>Strategy</span><b>${t.strategy_label}</b></div><div class="mrow"><span>Legs</span><b>${t.intent.legs.length}</b></div><div class="mrow"><span>${t.intent.price_effect}</span><b>$${t.intent.limit_price}</b></div><div class="mrow"><span>Preview ID</span><b>${state.complexPreviewId||"received"}</b></div>`:`<div class="mnote neg">${(j.errors||["Preview failed"]).join("; ")}</div>`;
      $("tccModalConfirm").style.display="none"; m.style.display="flex"; $("complexSubmit").disabled=!j.ok||!state.complexPreviewId; log(j.ok?"strategy preview approved — review then confirm and submit":"strategy preview blocked");
    } catch(e){log("strategy preview failed: "+e);}
  }

  async function submitComplexStrategy() {
    const t=state.complexTicket; if(!t||!state.complexPreviewId){log("successful preview required");return;}
    if(!window.confirm("Submit this " + t.strategy_label + " to E*TRADE now?")) return;
    const payload=Object.assign({},t,{confirmed:true,preview_id:state.complexPreviewId});
    try { const r=await fetch("/api/trade/spx/place-strategy",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}); const j=await r.json();
      log(j.ok?"complex strategy submitted":"submission blocked: "+(j.errors||[]).join("; ")); if(j.ok) $("complexSubmit").disabled=true;
    } catch(e){log("submission failed: "+e);}
  }

  // ── pre-flight order preview: run APEX risk guard (+ E*TRADE cost preview when live) ──
  async function previewOrder() {
    if (state.complexTicket) return previewComplexStrategy();
    if (!state.armed) { log("arm a plan first"); return; }
    const m = $("tccModal");
    $("tccModalTitle").textContent = "Preview Entry Order — pre-flight";
    $("tccModalConfirm").style.display = "none";     // placing is not wired in this build
    if (!state.contract || !state.contract.osi_key) {
      $("tccModalBody").innerHTML =
        `<div class="mnote neg">No live contract selected.</div>
         <div class="mnote">Pick a row from the SPX chain so the order has a real contract (osi key).
         A typed spot/premium/delta plan can be charted, but only a real contract can be previewed with the broker.</div>`;
      m.style.display = "flex";
      return;
    }
    const L = state.lines;
    const maxRisk = (L.ENTRY.prem - L.STOP.prem) * 100 * state.qty;
    $("tccModalBody").innerHTML =
      `<div class="mrow"><span>Contract</span><b>${state.contractLabel}</b></div>
       <div class="mrow"><span>Side / Qty</span><b>${state.side} × ${state.qty}</b></div>
       <div class="mrow"><span>Entry / Stop</span><b>$${fmt(L.ENTRY.prem)} / $${fmt(L.STOP.prem)}</b></div>
       <div class="mrow"><span>Targets</span><b>$${fmt(L.TP1.prem)} · $${fmt(L.TP2.prem)} · $${fmt(L.TP3.prem)}</b></div>
       <div class="mrow"><span>Max risk</span><b class="neg">${money(maxRisk)}</b></div>
       <div class="mnote">Running APEX pre-flight risk check…</div>`;
    m.style.display = "flex";
    try {
      const r = await fetch("/api/trade/spx/preview-entry", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contract: state.contract, quantity: state.qty,
          entry_premium: L.ENTRY.prem, stop_premium: L.STOP.prem,
          tp_prices: [L.TP1.prem, L.TP2.prem, L.TP3.prem],
          session_state: "MARKET_OPEN",
        }),
      });
      const j = await r.json();
      renderPreview(j);
    } catch (e) {
      const n = $("tccModalBody").querySelector(".mnote");
      if (n) n.outerHTML = `<div class="mnote neg">preview failed: ${e}</div>`;
    }
  }

  function renderPreview(j) {
    const risk = (j.data && j.data.risk) || {};
    const broker = (j.data && j.data.broker) || null;
    let html = "";
    // Risk verdict comes from the guard decision itself, not the overall ok
    // (the broker step can fail while the risk check passed).
    if (risk.allow) {
      html += `<div class="mnote pos">✓ Risk pre-check passed.</div>`;
    } else {
      const reasons = (risk.reasons && risk.reasons.length ? risk.reasons
                       : (j.errors && j.errors.length ? j.errors : ["blocked"])).join("; ");
      html += `<div class="mnote neg">✗ Risk pre-check: ${reasons}</div>`;
    }
    if (risk.warnings && risk.warnings.length) {
      html += `<div class="mnote warn">! ${risk.warnings.join("; ")}</div>`;
    }
    const cost = broker ? (broker.estimated_total_cost != null ? broker.estimated_total_cost
                 : (broker.total_cost != null ? broker.total_cost : broker.total)) : null;
    const hasBroker = !!(broker && (broker.preview_id || cost != null || broker.commission != null || broker.margin != null));
    if (hasBroker) {
      html += `<div class="mrow" style="margin-top:8px"><span>Broker preview</span><b>${broker.preview_id ? "id " + broker.preview_id : "received"}</b></div>`;
      if (cost != null) html += `<div class="mrow"><span>Est. cost</span><b>${money(cost)}</b></div>`;
      if (broker.commission != null) html += `<div class="mrow"><span>Commission</span><b>$${fmt(broker.commission)}</b></div>`;
      if (broker.margin != null) html += `<div class="mrow"><span>Margin</span><b>${money(broker.margin)}</b></div>`;
    } else {
      const berr = (risk.allow && !j.ok && j.errors && j.errors.length) ? j.errors.join("; ") : null;
      html += berr
        ? `<div class="mnote">Broker cost preview unavailable: ${berr}</div>`
        : `<div class="mnote">Broker cost preview appears here once E*TRADE is connected (Configured: YES) during market hours.</div>`;
    }
    html += `<div class="mnote" style="opacity:.65">Pre-flight uses regular-hours rules. Live placement re-checks the current session — and placing stays disabled until you explicitly enable it.</div>`;
    const n = $("tccModalBody").querySelector(".mnote");
    if (n) n.outerHTML = html;
  }

  // ── selecting a contract from the chain table autofills the plan ───────────────
  window.tccSelectContract = function (c) {
    state.side = (c.side || "CALL").toUpperCase();
    state.contract = c;
    state.contractLabel = (c.display_symbol || ("SPX " + c.strike + " " + state.side));
    if (c.mid != null) $("tccPrem").value = c.mid;
    if (c.delta != null) $("tccDelta").value = c.delta;
    state.contractLabel && ($("ccContract").textContent = state.contractLabel);
    log("selected " + state.contractLabel + " — set spot then Arm Plan");
  };

  // ── util ───────────────────────────────────────────────────────────────────────
  const fmt = (v) => (v == null ? "—" : (Math.abs(v) < 1 ? (+v).toFixed(3) : (+v).toFixed(2)));
  const money = (v) => (v < 0 ? "-$" : "$") + Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
  function log(m) { const el = $("tccLog"); if (el) el.textContent = "[" + new Date().toLocaleTimeString() + "] " + m + "\n" + el.textContent; }

  // ── boot ───────────────────────────────────────────────────────────────────────
  function boot() {
    if (!LWC) { log("Lightweight Charts failed to load"); return; }
    initCharts();
    $("tccArm").addEventListener("click", armPlan);
    $("tccModeBtn").addEventListener("click", toggleMode);
    $("tccModalClose").addEventListener("click", closeModal);
    const pv = $("tccPreview"); if (pv) pv.addEventListener("click", previewOrder);
    const cp=$("complexPreview"); if(cp) cp.addEventListener("click",previewComplexStrategy);
    const cs=$("complexSubmit"); if(cs) cs.addEventListener("click",submitComplexStrategy);
    $("tccReload").addEventListener("click", loadCandles);
    document.querySelectorAll("[data-tccTf]").forEach((b) =>
      b.addEventListener("click", () => setTf(parseInt(b.getAttribute("data-tccTf"), 10))));
    document.querySelectorAll("[data-tccLb]").forEach((b) =>
      b.addEventListener("click", () => setLookback(parseInt(b.getAttribute("data-tccLb"), 10))));
    const zi = $("tccZoomIn"), zo = $("tccZoomOut"), ft = $("tccFit");
    if (zi) zi.addEventListener("click", () => zoom(0.6));
    if (zo) zo.addEventListener("click", () => zoom(1.6));
    if (ft) ft.addEventListener("click", fitAll);
    loadCandles();
    log("command center ready — pick a contract or enter spot/premium/delta, then Arm Plan");
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();

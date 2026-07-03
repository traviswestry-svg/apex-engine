let osLoading = false;
/**
 * APEX Institutional OS — 6.2.2 frontend route stability
 * Reads from /api/institutional_os  (nine-engine pipeline)
 * Panels: Ribbon · ICI · Decision · Trade Coach · Engine Matrix
 *         Flow Intelligence 2.0 · Story Engine · Replay · Review
 */

/* ── State ────────────────────────────────────────────────────────────────── */
let osData       = null;
let replaySnaps  = [];     // array of timestamped snapshots for replay
let replayIdx    = 0;
let replayPlaying = false;
let replayTimer   = null;
let reviewLog     = [];    // session review entries stored in memory
let confidenceLog = [];    // server-backed ICI timeline for command center
let activeTicker  = new URLSearchParams(location.search).get('ticker') || 'SPX';
const AUTO_INTERVAL = 12000; // ms between auto-refreshes

/* ── Utilities ────────────────────────────────────────────────────────────── */
const $ = id => document.getElementById(id);
const fmt  = v  => v != null ? Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '--';
const fmtI = v  => v != null ? Number(v).toFixed(0) : '--';
const fmtM = v  => { const n = Number(v); if (!isFinite(n)) return '--'; if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1) + 'M'; if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(0) + 'K'; return n.toFixed(0); };
const clr  = (v, hi, lo) => v >= hi ? 'var(--green)' : v <= lo ? 'var(--red)' : 'var(--amber)';
const html = s => s != null ? String(s) : '--';
const esc  = s => String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

/* ── Clock ────────────────────────────────────────────────────────────────── */
(function clock() {
  const et = new Intl.DateTimeFormat('en-US', {
    hour: 'numeric', minute: '2-digit', second: '2-digit',
    hour12: true, timeZone: 'America/New_York'
  }).format(new Date());
  const el = $('clockEl'); if (el) el.textContent = et + ' ET';
  setTimeout(clock, 1000);
})();

/* ── Tab system ───────────────────────────────────────────────────────────── */
function initTabs() {
  // Only bind the feature dashboard tabs. Ticker buttons also use .tab-btn for
  // styling, but they do not have data-tab. Binding them here caused clicks on
  // SPX/SPY/QQQ/IWM to set target=undefined and deactivate every tab pane,
  // which made Dashboard, Flow Intelligence, Story, Replay, and Review appear
  // broken after the 6.2.0 upgrade.
  document.querySelectorAll('.tab-btn[data-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.tab;
      if (!target) return;
      document.querySelectorAll('.tab-btn[data-tab]').forEach(b => {
        b.classList.toggle('active', b.dataset.tab === target);
      });
      document.querySelectorAll('.tab-pane').forEach(p => {
        p.classList.toggle('active', p.id === 'tab-' + target);
      });
    });
  });
}

/* ════════════════════════════════════════════════════════════════════════════
   SPRINT 6.0.3 — RIBBON, ICI, TRADE COACH, ENGINE MATRIX
   ════════════════════════════════════════════════════════════════════════════ */

/* ── Ribbon ───────────────────────────────────────────────────────────────── */
function renderRibbon(d) {
  const el = $('ribbon');
  if (!el || !d) return;
  const r   = d.ribbon  || {};
  const ici = d.ici     || {};
  const fl  = d.flow_intelligence || d.flow || {};
  const g   = d.gamma_regime || {};
  const ms  = d.market_state || {};
  const ai  = d.auction_intelligence || {};
  const dec = d.decision_state || '';
  const str = d.structure || {};

  const decCls  = dec.includes('CALL') ? 'rv-green' : dec.includes('PUT') ? 'rv-red' : dec.includes('WATCH') || dec === 'READY' ? 'rv-amber' : 'rv-muted';
  const cellCls = dec.includes('CALL') ? 'rdc-call' : dec.includes('PUT') ? 'rdc-put' : dec.includes('WATCH') || dec === 'READY' ? 'rdc-watch' : 'rdc-no';

  const poc     = ms.poc || str.session_poc || 0;
  const vwap    = ms.vwap || r.vwap || str.vwap || 0;
  const pocMig  = ms.poc_migration || '';
  const pvp     = ms.price_vs_poc  || '';
  const pva     = ms.price_vs_va   || '';
  const net_flow = r.net_flow || 0;
  const price    = ms.price || r.spx_price || fl.stock_price || 0;

  // ── Auction synthesis ──
  const aiState  = (ai.auction_state || {});
  const aiAcc    = (ai.acceptance    || {});
  const aiPoc    = (ai.poc_migration || {});
  const accStatus = aiAcc.primary_status || '';
  const auctionName = (aiState.state || '').replace(/_/g,' ');
  const pocDelta  = aiPoc.delta || 0;
  const pocArrow  = pocMig === 'RISING' ? '▲' : pocMig === 'FALLING' ? '▼' : '—';
  const pocColor  = pocMig === 'RISING' ? 'var(--green)' : pocMig === 'FALLING' ? 'var(--red)' : 'var(--muted)';
  const accColor  = accStatus === 'ACCEPTING' ? 'var(--green)' : accStatus === 'REJECTED' ? 'var(--red)' : 'var(--amber)';

  // Auction cell label: "Accepting Higher" / "Accepting Lower" / "Rejecting" / "Balanced"
  const auctionVerb =
    pva === 'ABOVE_VAH' && pocMig === 'RISING'   ? 'Accepting Higher' :
    pva === 'ABOVE_VAH' && pocMig !== 'RISING'   ? 'Testing Higher'   :
    pva === 'BELOW_VAL' && pocMig === 'FALLING'  ? 'Accepting Lower'  :
    pva === 'BELOW_VAL' && pocMig !== 'FALLING'  ? 'Testing Lower'    :
    accStatus === 'REJECTED'                      ? 'Rejecting'        :
    pocMig === 'RISING'                           ? 'POC Rising'       :
    pocMig === 'FALLING'                          ? 'POC Falling'      : 'Balanced';

  const auctionVerbColor =
    auctionVerb.includes('Accepting Higher') || auctionVerb.includes('POC Rising') ? 'var(--green)' :
    auctionVerb.includes('Accepting Lower')  || auctionVerb.includes('POC Falling') || auctionVerb.includes('Rejecting') ? 'var(--red)' :
    auctionVerb.includes('Testing') ? 'var(--amber)' : 'var(--muted)';

  // Auction confidence from auction state engine
  const auctionConf = aiState.confidence || 0;

  // POC delta string: "+1.75" or "-3.25"
  const pocDeltaStr = pocDelta !== 0 ? (pocDelta > 0 ? '+' : '') + pocDelta.toFixed(2) : '';

  // ── Gamma flip proximity ──
  const zeroGamma = ms.zero_gamma || g.zero_gamma || r.zero_gamma || 0;
  const flipProx  = ms.flip_proximity || (zeroGamma > 0 && price > 0 ? Math.abs(price - zeroGamma) : null);
  const flipPct   = flipProx != null && price > 0 ? (flipProx / price * 100).toFixed(2) : null;
  const flipWarn  = flipProx != null && flipProx < 15;
  const flipColor = flipProx != null && flipProx < 5 ? 'var(--red)' : flipProx != null && flipProx < 10 ? 'var(--amber)' : 'var(--muted)';
  const gammaSubLabel = flipWarn && flipPct
    ? `Within ${flipPct}% of flip ⚡`
    : (g.regime_display || '').split(' ').slice(0,2).join(' ') || '--';

  // ── Flow pressure line ──
  const flowBias   = ms.flow_bias || fl.bias || 'MIXED';
  const tapeBias   = ms.tape_bias || '';
  const sweeps     = ms.tape_sweeps || 0;
  const netPrem    = ms.net_premium || net_flow || 0;
  const darkPool   = fl.block_conviction || '';

  // "Bullish options premium · sweep pressure" style sub-label
  const flowPressure = (() => {
    const parts = [];
    if (flowBias === 'BULLISH') parts.push('Bullish options premium');
    else if (flowBias === 'BEARISH') parts.push('Bearish options pressure');
    else parts.push('Mixed flow');
    if (sweeps >= 3) parts.push(`${sweeps} sweeps`);
    if (darkPool && darkPool !== 'NONE') parts.push('Block conviction');
    return parts.join(' · ');
  })();

  // Relative strength — QQQ vs SPY proxy from structure
  const rsLabel = (() => {
    const qqq_rel = fl.qqq_relative_strength || ms.qqq_relative_strength || null;
    if (qqq_rel === 'LEADING')  return 'Tech leading ↑';
    if (qqq_rel === 'LAGGING')  return 'Tech lagging ↓';
    return tapeBias ? `Tape: ${tapeBias}` : '';
  })();

  el.innerHTML = `
    <div class="ribbon-cell">
      <div class="ribbon-label">SPX Price</div>
      <div class="ribbon-val rv-blue">$${fmt(price)}</div>
      <div class="ribbon-sub">${activeTicker} · ES $${fmt(r.es_price || ms.es_price || price)}</div>
    </div>

    <div class="ribbon-cell ribbon-auction-cell">
      <div class="ribbon-label">Auction</div>
      <div class="ribbon-val" style="font-size:13px;font-weight:900;color:${auctionVerbColor}">${esc(auctionVerb)}</div>
      <div class="ribbon-sub">
        <span style="color:${pocColor};font-weight:700">${pocArrow} POC${pocDeltaStr ? ' '+pocDeltaStr+'pts' : ''}</span>
        ${auctionConf > 0 ? ` · ${auctionConf}%` : ''}
      </div>
    </div>

    <div class="ribbon-cell">
      <div class="ribbon-label">Acceptance</div>
      <div class="ribbon-val" style="font-size:12px;color:${accColor};font-weight:800">${accStatus || '--'}</div>
      <div class="ribbon-sub">${esc(aiAcc.primary_level || (poc > 0 ? 'POC $'+fmt(poc) : '--'))}</div>
    </div>

    <div class="ribbon-cell">
      <div class="ribbon-label">Call Wall</div>
      <div class="ribbon-val rv-green">$${fmt(r.call_wall || g.call_wall || ms.call_wall)}</div>
      <div class="ribbon-sub">Put: $${fmt(r.put_wall || g.put_wall || ms.put_wall)}</div>
    </div>

    <div class="ribbon-cell ${flipWarn ? 'ribbon-cell-warn' : ''}">
      <div class="ribbon-label">Gamma Flip</div>
      <div class="ribbon-val" style="color:${flipWarn ? flipColor : 'var(--amber)'}">$${fmt(zeroGamma)}</div>
      <div class="ribbon-sub" style="color:${flipWarn ? flipColor : 'var(--faint)'}">${esc(gammaSubLabel)}</div>
    </div>

    <div class="ribbon-cell">
      <div class="ribbon-label">Inst. Flow</div>
      <div class="ribbon-val ${net_flow >= 0 ? 'rv-green' : 'rv-red'}">$${fmtM(net_flow)}</div>
      <div class="ribbon-sub ribbon-flow-pressure" title="${esc(flowPressure)}">${esc(flowPressure.length > 28 ? flowPressure.slice(0,27)+'…' : flowPressure)}</div>
    </div>

    <div class="ribbon-cell">
      <div class="ribbon-label">VWAP</div>
      <div class="ribbon-val rv-blue">$${fmt(vwap)}</div>
      <div class="ribbon-sub">${poc > 0 ? 'POC $'+fmt(poc) : '--'}${rsLabel ? ' · '+esc(rsLabel) : ''}</div>
    </div>

    <div class="ribbon-cell">
      <div class="ribbon-label">ICI</div>
      <div class="ribbon-val ${ici.ici_color === 'GREEN' ? 'rv-green' : ici.ici_color === 'RED' ? 'rv-red' : 'rv-amber'}">${fmtI(ici.ici)}</div>
      <div class="ribbon-sub">${ici.ici_label || '--'} · ${d.grade || '--'}</div>
    </div>

    <div class="ribbon-cell ribbon-decision ${cellCls}">
      <div class="ribbon-label">Decision</div>
      <div class="ribbon-val ${decCls}" style="font-size:11px;margin-top:5px;letter-spacing:.02em">${(dec || 'LOADING').replace(/_/g,' ')}</div>
      <div class="ribbon-sub">${d.readiness ? d.readiness.replace(/_/g,' ') : '--'}</div>
    </div>
  `;
}

/* ── Institutional Confidence Index ───────────────────────────────────────── */
function renderICI(d) {
  const el = $('iciPanel');
  if (!el || !d) return;
  const ici     = d.ici || {};
  const score   = Number(ici.ici || 0);
  const comps   = ici.components || {};
  const wts     = ici.weights    || {};
  const ms      = d.market_state || {};
  const session = (d.session || {}).session_state || ms.session_state || '';
  const scoreColor = ici.ici_color === 'GREEN' ? 'var(--green)' : ici.ici_color === 'RED' ? 'var(--red)' : 'var(--amber)';

  // Session context label for the ICI — explains low scores are EXPECTED
  const sessionCtx = (() => {
    if (session === 'CLOSED')      return { label: 'CLOSED SESSION',    note: 'Expected. Recalculates after cash open.' };
    if (session === 'OVERNIGHT')   return { label: 'OVERNIGHT',         note: 'Execution engine inactive. ES monitoring only.' };
    if (session === 'PREMARKET')   return { label: 'PRE-MARKET',        note: 'Building confidence before 9:30 ET.' };
    if (session === 'AFTER_HOURS') return { label: 'AFTER-HOURS',       note: 'Review mode. No new entries.' };
    if (score < 30)                return { label: 'LOW CONVICTION',    note: 'Sit out until engines align.' };
    if (score < 55)                return { label: 'BUILDING',          note: 'Partial alignment — watch mode.' };
    if (score < 70)                return { label: 'MODERATE',          note: 'Some alignment — Pine needed.' };
    return { label: ici.ici_label || 'HIGH', note: 'All systems aligned.' };
  })();

  // Update the big ICI number in the status bar
  const readEl = $('readinessNum');
  if (readEl) {
    readEl.textContent = fmtI(score);
    readEl.className = 'dsb-ici-num';
    readEl.style.color = scoreColor;
  }

  // Compact component bars + context label
  const compDefs = [
    { key: 'conviction',      label: 'Consensus', w: wts.conviction || 0.5  },
    { key: 'freshness',       label: 'Signal',    w: wts.freshness  || 0.2  },
    { key: 'gamma_stability', label: 'Gamma',     w: wts.gamma      || 0.15 },
    { key: 'flow_momentum',   label: 'Flow',      w: wts.momentum   || 0.15 },
  ];

  const barsHTML = compDefs.map(c => {
    const val = Number(comps[c.key] || 0);
    const barColor = val >= 70 ? 'var(--green)' : val >= 45 ? 'var(--blue)' : 'var(--red)';
    return `<div class="dsb-comp">
      <div class="dsb-comp-header">
        <span class="dsb-comp-label">${c.label}</span>
        <span class="dsb-comp-val" style="color:${barColor}">${val.toFixed(0)}</span>
      </div>
      <div class="dsb-comp-bar"><div style="width:${val}%;background:${barColor}"></div></div>
    </div>`;
  }).join('');

  // Drive the confidence meter fill bar
  const fillEl = $('iciFill');
  if (fillEl) {
    fillEl.style.width = Math.min(score, 100) + '%';
    fillEl.style.background = scoreColor;
  }
  const ctxEl = $('iciCtxLabel');
  if (ctxEl) {
    ctxEl.textContent = sessionCtx.label;
    ctxEl.style.color = scoreColor;
  }

  // Compact component bars in the new op-ici-comps slot
  el.innerHTML = barsHTML + `
    <div class="dsb-session-ctx">
      <span class="dsb-ctx-note">${esc(sessionCtx.note)}</span>
    </div>
    <div class="dsb-grade" style="color:${score>=85?'var(--green)':score>=70?'var(--blue)':score>=55?'var(--amber)':'var(--red)'}">${d.grade||'--'}</div>`;
}

/* ── Decision + Signal Decay ──────────────────────────────────────────────── */
function renderDecision(d) {
  if (!d) return;
  const dec    = d.decision || {};
  const state  = d.decision_state || dec.state || 'PREPARING';
  const ici    = d.ici || {};
  const exec   = d.execution || {};
  const cons   = d.consensus || {};

  // Badge
  const badge = $('decisionBadge');
  if (badge) {
    const cls = state.includes('CALL') ? 'db-call' : state.includes('PUT') ? 'db-put' : state.includes('WATCH') || state === 'READY' ? 'db-caution' : 'db-neutral';
    const arrow = state.includes('CALL') ? '▲ ' : state.includes('PUT') ? '▼ ' : '— ';
    badge.className = 'decision-badge ' + cls;
    badge.textContent = arrow + state.replace(/_/g, ' ');
  }

  // Confidence number
  const confEl = $('confNum');
  if (confEl) {
    const conf = Number(ici.ici || 0);
    confEl.textContent = fmtI(conf);
    confEl.style.color = conf >= 70 ? 'var(--green)' : conf >= 50 ? 'var(--amber)' : 'var(--red)';
  }

  // Executive summary
  const msgEl = $('decisionMsg');
  if (msgEl) msgEl.textContent = d.executive_summary || dec.message || '--';

  // Action
  const actEl = $('decisionAction');
  if (actEl) actEl.textContent = cons.action || dec.action || '';

  // Signal decay bar
  const secs = Number(exec.signal_seconds_remaining || dec.signal_seconds_remaining || 0);
  const ttl  = Number(exec.signal_ttl_seconds || dec.signal_ttl_seconds || 360);
  const pct  = ttl > 0 ? Math.round(secs / ttl * 100) : 0;
  const decayEl = $('decayBar');
  if (decayEl) {
    decayEl.style.width  = pct + '%';
    decayEl.style.background = pct > 60 ? 'var(--green)' : pct > 30 ? 'var(--amber)' : 'var(--red)';
  }
  const ageEl = $('decayAge'); if (ageEl) ageEl.textContent = secs > 0 ? secs + 's left' : 'No signal';
  const expEl = $('decayExp'); if (expEl) expEl.textContent = exec.signal_fresh ? 'Live' : 'Expired';

  // Gate checklist — use decision.checklist if available, otherwise derive
  const gcEl = $('gateChecks');
  if (gcEl) {
    const gates = dec.checklist || [
      { label: 'ICI ≥ 70', ok: Number(ici.ici || 0) >= 70 },
      { label: 'Consensus directional', ok: ['BULLISH','BEARISH'].includes(cons.consensus_direction) },
      { label: 'Pine confirmation', ok: !!exec.signal_matches_flow },
      { label: 'No A+ divergence block', ok: (d.divergence_type) !== 'A_PLUS' },
    ];
    const passCount = gates.filter(g => g.ok).length;
    // readinessNum is owned by renderICI — do not overwrite it here
    const isNoTrade = state === 'NO_TRADE' || state === 'PREPARING';
    const isEnter   = state.startsWith('ENTER');
    const passCount2 = gates.filter(g => g.ok).length;
    const passGates  = gates.filter(g => g.ok);
    const failGates  = gates.filter(g => !g.ok);

    // Update the "Why" label
    const whyLabelEl = $('whyLabel');
    if (whyLabelEl) {
      whyLabelEl.textContent = isEnter ? 'Enter Because' : isNoTrade ? 'Blocked By' : 'Gates';
      whyLabelEl.style.color = isEnter ? 'var(--green)' : isNoTrade ? 'var(--red)' : 'var(--muted)';
    }

    // What's needed to get to an entry
    const needed = (() => {
      const n = [];
      if (!exec.signal_matches_flow && !exec.has_signal) n.push('Pine confirmation');
      if (!['BULLISH','BEARISH'].includes(cons.consensus_direction)) n.push('Directional flow');
      if (Number(ici.ici || 0) < 70) n.push('ICI ≥ 70');
      return n;
    })();

    if (isEnter) {
      // ENTER BECAUSE — show passing gates with checkmarks
      gcEl.innerHTML = passGates.map(g =>
        `<div class="why-gate why-gate-pass">✓ ${esc(g.label)}</div>`
      ).concat(failGates.map(g =>
        `<div class="why-gate why-gate-fail">✗ ${esc(g.label)}</div>`
      )).join('');
    } else if (isNoTrade && failGates.length > 0) {
      // NO TRADE BECAUSE — show blockers + what's needed
      gcEl.innerHTML = failGates.map(g =>
        `<div class="why-gate why-gate-fail">✗ ${esc(g.label)}</div>`
      ).join('') +
      (needed.length ? needed.map(n =>
        `<div class="why-gate why-gate-need">→ ${esc(n)}</div>`
      ).join('') : '');
    } else {
      gcEl.innerHTML = gates.map(g =>
        `<div class="why-gate ${g.ok ? 'why-gate-pass' : 'why-gate-fail'}">${g.ok ? '✓' : '✗'} ${esc(g.label)}</div>`
      ).join('');
    }
  }
}

/* ── Trade Coach ──────────────────────────────────────────────────────────── */
function renderTradeCoach(d) {
  const el = $('tradeCoach');
  if (!el || !d) return;
  const tc   = d.trade_coach || {};
  const risk = d.risk        || {};
  const side = tc.approved_side || risk.approved_side || 'NONE';
  const sideCls = side === 'CALL' ? 'cp-call' : side === 'PUT' ? 'cp-put' : '';

  const planItems = [
    { cls: 'cp-entry', label: 'Contract',  val: tc.contract_hint || risk.contract_hint },
    { cls: 'cp-entry', label: 'Entry Zone', val: tc.entry_zone    || risk.entry_zone },
    { cls: 'cp-stop',  label: 'Stop',       val: tc.stop          || risk.stop },
    { cls: 'cp-t1',    label: 'Target 1',   val: tc.target1       || risk.target1 },
    { cls: 'cp-t2',    label: 'Target 2',   val: tc.target2       || risk.target2 },
    { cls: 'cp-entry', label: 'Γ Management', val: tc.gamma_management },
  ].filter(i => i.val != null);

  const planHTML = planItems.map(i =>
    `<div class="cp-item ${i.cls}"><div class="cp-label">${i.label}</div><div class="cp-val">${esc(i.val)}</div></div>`
  ).join('');

  const blockersHTML = (tc.blockers || []).length
    ? '<div class="coach-blockers">' + tc.blockers.map(b =>
        `<div class="blocker-item">⚠ ${esc(b)}</div>`).join('') + '</div>'
    : '';

  el.innerHTML = `
    <div class="coach-action">${esc(tc.action || risk.approved_side ? 'Awaiting coach output...' : 'No trade — sit out.')}</div>
    ${planItems.length ? `<div class="coach-plan">${planHTML}</div>` : ''}
    ${blockersHTML}
    ${tc.gamma_management ? `<div class="coach-gamma-note">Gamma rule: ${esc(tc.gamma_management)}</div>` : ''}
    ${tc.next_confirmation ? `<div class="coach-next">→ ${esc(tc.next_confirmation)}</div>` : ''}
  `;
}

/* ── Engine Matrix ────────────────────────────────────────────────────────── */
function renderEngineMatrix(d) {
  const el = $('engineMatrix');
  if (!el || !d) return;
  const contribs = d.engine_contributions || [];
  const cons = d.consensus || {};

  // Consensus bar
  const nBull = cons.n_bullish || 0;
  const nBear = cons.n_bearish || 0;
  const nNeut = cons.n_neutral || 0;
  const consEl = $('consensusBar');
  if (consEl) {
    const iciW = (d.ici || {}).weights || {};
    const sessState = (d.session || {}).session_state || ms.session_state || '';
    const sessBadge = sessState !== 'MARKET_OPEN'
      ? `<span style="font-size:9px;padding:1px 6px;border-radius:4px;background:rgba(245,158,11,.12);color:var(--amber);margin-left:6px;font-weight:700">${sessState.replace(/_/g,' ')} — adaptive weights active</span>`
      : '';
    consEl.innerHTML =
      '<div class="consensus-bars">' +
        '<div class="cb-bull" style="flex:' + nBull + '"></div>' +
        '<div class="cb-neut" style="flex:' + nNeut + '"></div>' +
        '<div class="cb-bear" style="flex:' + nBear + '"></div>' +
      '</div>' +
      '<div class="consensus-meta">' +
        '<span style="color:var(--green)">▲ ' + nBull + ' Bull</span>' +
        '<span>' + esc(cons.consensus_label || '--') + sessBadge + '</span>' +
        '<span style="color:var(--red)">▼ ' + nBear + ' Bear</span>' +
      '</div>';
  }

  if (!contribs.length) {
    el.innerHTML = '<div style="color:var(--faint);font-size:12px;padding:10px">No engine data yet.</div>';
    return;
  }

  el.innerHTML = contribs.map((e, idx) => {
    const score = e.score != null ? Number(e.score) : null;
    const vote  = (e.vote || 'NEUTRAL').toUpperCase();
    const health = (e.health_status || 'OK').toUpperCase();
    const dataAv = e.data_available !== false;

    // Vote badge
    let voteCls, voteLabel;
    if (!dataAv || vote === 'UNAVAILABLE') {
      voteCls  = 'ev-neut'; voteLabel = '⏳ WAIT';
    } else if (vote === 'BULLISH') {
      voteCls = 'ev-bull'; voteLabel = '▲ BULL';
    } else if (vote === 'BEARISH') {
      voteCls = 'ev-bear'; voteLabel = '▼ BEAR';
    } else {
      voteCls = 'ev-neut'; voteLabel = '— NEUT';
    }

    // Health dot
    const healthColor = health === 'OK' ? 'var(--green)'
      : health === 'NO_SIGNAL' ? 'var(--amber)'
      : health === 'WAITING' || health === 'SKIPPED' ? 'var(--faint)' : 'var(--red)';
    const healthDot = '<span style="width:7px;height:7px;border-radius:50%;background:' + healthColor + ';display:inline-block;margin-right:4px;flex-shrink:0"></span>';

    // Score bar
    const barPct  = score != null ? score : 0;
    const barColor = !dataAv ? 'var(--bdr)'
      : barPct >= 65 ? 'var(--green)'
      : barPct >= 45 ? 'var(--blue)' : 'var(--red)';
    const scoreDisp = score != null ? score.toFixed(0) : '--';

    // Weight and contribution
    const wt   = e.weight  != null ? (e.weight * 100).toFixed(1) + '%' : '--';
    const cont = e.contribution != null ? e.contribution.toFixed(3) : '--';

    // Timestamp
    const ts = e.sampled_at || '--';

    const notes = (e.notes || []).slice(0, 3);
    const notesHTML = notes.length
      ? '<div class="em-notes" id="em-notes-' + idx + '">' +
          notes.map(n => '<div class="em-note-item">· ' + esc(n) + '</div>').join('') +
          '<div class="em-note-item" style="color:var(--faint)">Sampled ' + ts + ' · Weight ' + wt + ' · Contribution ' + cont + '</div>' +
        '</div>'
      : '';

    const rowStyle = !dataAv ? 'opacity:0.55' : '';

    return (
      '<div class="em-row" id="em-row-' + idx + '" onclick="toggleEmRow(' + idx + ',' + (notes.length > 0 || !dataAv) + ')" style="cursor:pointer;' + rowStyle + '">' +
        '<div class="em-name">' + healthDot + esc(e.label || e.engine) + '</div>' +
        '<div class="em-vote ' + voteCls + '">' + voteLabel + '</div>' +
        '<div class="em-bar-wrap"><div class="em-bar" style="width:' + barPct + '%;background:' + barColor + '"></div></div>' +
        '<div class="em-score">' + scoreDisp + '</div>' +
      '</div>' +
      notesHTML
    );
  }).join('');

  // Engine Health summary panel
  const healthEl = $('engineHealthPanel');
  if (healthEl) renderEngineHealth(contribs);
}

function toggleEmRow(idx, hasNotes) {
  const row   = $('em-row-' + idx);
  const notes = $('em-notes-' + idx);
  if (!row || !notes) return;
  row.classList.toggle('expanded');
  notes.style.display = row.classList.contains('expanded') ? 'flex' : 'none';
}

/* ── Engine Health Panel ───────────────────────────────────────────────────── */
function renderEngineHealth(contribs) {
  const el = $('engineHealthPanel');
  if (!el || !contribs) return;

  const rows = contribs.map(e => {
    const health = (e.health_status || 'OK').toUpperCase();
    const dataAv = e.data_available !== false;
    const col = health === 'OK' ? 'var(--green)'
      : health === 'NO_SIGNAL' ? 'var(--amber)'
      : 'var(--faint)';
    const icon = health === 'OK' ? '●' : health === 'NO_SIGNAL' ? '◐' : '○';
    return (
      '<div style="display:flex;align-items:center;gap:7px;padding:4px 0;border-bottom:1px solid var(--bdr);font-size:11px">' +
        '<span style="color:' + col + ';font-size:10px;width:10px">' + icon + '</span>' +
        '<span style="color:var(--muted);min-width:120px">' + esc(e.label) + '</span>' +
        '<span style="font-family:var(--mono);font-size:10px;color:' + col + ';font-weight:700">' + health + '</span>' +
        '<span style="font-family:var(--mono);font-size:9px;color:var(--faint);margin-left:auto">' + (e.sampled_at || '--') + '</span>' +
      '</div>'
    );
  }).join('');

  const allOk = contribs.every(e => (e.health_status || 'OK') === 'OK');
  const waiting = contribs.filter(e => ['WAITING','SKIPPED','NO_SIGNAL'].includes(e.health_status || '')).length;
  const summary = allOk
    ? '<span style="color:var(--green);font-size:10px;font-weight:700">● All engines healthy</span>'
    : '<span style="color:var(--amber);font-size:10px;font-weight:700">◐ ' + waiting + ' engine(s) waiting / skipped</span>';

  el.innerHTML = summary + '<div style="margin-top:6px">' + rows + '</div>';
}

/* ── Session status / heatmap ─────────────────────────────────────────────── */
function renderSession(d) {
  const sess = d.session || {};
  const pill = $('sessionPill');
  if (pill) {
    const s = sess.session_state || '';
    pill.textContent = s.replace(/_/g, ' ') || 'LOADING';
    pill.className = 'session-pill ' + (s === 'MARKET_OPEN' ? 'sess-open' : 'sess-closed');
  }
  const tickEl = $('tickerLabel');
  if (tickEl) tickEl.textContent = activeTicker;
}

function renderHeatmap(d) {
  const el = $('heatGrid');
  if (!el) return;
  const hm = d.heatmap || {};
  const tickers = hm.tickers || [];
  if (!tickers.length) { el.innerHTML = '<div style="color:var(--faint);font-size:11px">No heatmap data.</div>'; return; }
  el.innerHTML = tickers.map(t => {
    const cls = t.action_class === 'enter' ? 'h-enter' : t.action_class === 'watch' ? 'h-watch' : t.action_class === 'wait' ? 'h-wait' : 'h-no';
    return `<div class="heat-item ${cls}">
      <div class="heat-ticker">${esc(t.ticker)}</div>
      <div class="heat-score">${fmtI(t.score)}</div>
      <div class="heat-action">${esc(t.action || '--')}</div>
    </div>`;
  }).join('');
}

function recordConfidencePoint(d) {
  if (!d) return;
  const ici = Number((d.ici || {}).ici || d.confidence || 0);
  const state = d.decision_state || (d.decision || {}).state || 'NO_TRADE';
  const price = (d.ribbon || {}).spx_price || ((d.flow || {}).stock_price) || null;
  const ts = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'America/New_York' });
  const last = confidenceLog[confidenceLog.length - 1];
  if (last && last.state === state && Math.abs(last.ici - ici) < 0.1 && Math.abs((last.price || 0) - (price || 0)) < 0.01) return;
  confidenceLog.push({ ts, ici, state, price });
  if (confidenceLog.length > 20) confidenceLog.shift();
}

function renderCommandCenter(d) {
  const el = $('commandCenter');
  if (!el || !d) return;
  // Command Center now focuses on POC and auction — not a list of metrics
  const ms    = d.market_state || {};
  const ai    = d.auction_intelligence || {};
  const au    = d.auction || {};
  const state = d.decision_state || 'NO_TRADE';
  const ici   = Number((d.ici || {}).ici || 0);
  const price = ms.price || (d.ribbon || {}).spx_price || 0;

  // POC context
  const poc   = ms.poc || (au.poc) || 0;
  const vah   = ms.vah || (au.vah) || 0;
  const val_  = ms.val || (au.val) || 0;
  const mig   = ms.poc_migration || au.poc_migration || 'UNKNOWN';
  const pvp   = ms.price_vs_poc || '';
  const pva   = ms.price_vs_va  || '';
  const pocDelta = (ai.poc_migration || {}).delta || 0;
  const pocSpeed = (ai.poc_migration || {}).speed || '';
  const pocAccel = (ai.poc_migration || {}).acceleration || '';

  // Auction state
  const aiState = (ai.auction_state || {});
  const auctionName = (aiState.state || au.auction_state || 'UNKNOWN').replace(/_/g,' ');
  const isInit  = aiState.is_initiative;
  const isResp  = aiState.is_responsive;
  const isTrend = aiState.is_trend_day;
  const wouldTrade = aiState.would_trade;
  const auctionConf = aiState.confidence || 0;

  // Acceptance
  const accStatus = (ai.acceptance || {}).primary_status || '';
  const accLevel  = (ai.acceptance || {}).primary_level  || '';

  // Excess
  const excess    = (ai.excess || {}).detected ? (ai.excess.type || '').replace(/_/g,' ') : '';

  // Colors
  const decCls  = state.includes('CALL') ? 'cmd-call' : state.includes('PUT') ? 'cmd-put' : state.includes('WATCH') || state === 'READY' ? 'cmd-watch' : 'cmd-no';
  const pocColor = mig === 'RISING' ? 'var(--green)' : mig === 'FALLING' ? 'var(--red)' : 'var(--muted)';
  const pocArrow = mig === 'RISING' ? '▲' : mig === 'FALLING' ? '▼' : '—';
  const pvaColor = pva === 'ABOVE_VAH' ? 'var(--green)' : pva === 'BELOW_VAL' ? 'var(--red)' : 'var(--muted)';
  const iciColor = ici >= 75 ? 'var(--green)' : ici >= 55 ? 'var(--amber)' : 'var(--red)';
  const accColor = accStatus === 'ACCEPTING' ? 'var(--green)' : accStatus === 'REJECTED' ? 'var(--red)' : 'var(--amber)';
  const auctionColor = isTrend ? 'var(--green)' : isInit ? '#22d3ee' : isResp ? 'var(--amber)' : 'var(--muted)';

  // POC delta display
  const deltaPts = pocDelta !== 0 ? (pocDelta > 0 ? '+' : '') + pocDelta.toFixed(2) + ' pts' : '';

  // Location plain english
  const locText =
    pva === 'ABOVE_VAH' ? 'Above Value' :
    pva === 'BELOW_VAL' ? 'Below Value' :
    pvp === 'ABOVE'     ? 'Inside — Above POC' :
    pvp === 'BELOW'     ? 'Inside — Below POC' : 'At POC';

  el.innerHTML = `
    <div class="cmd-decision ${decCls}">${esc(state.replace(/_/g,' '))}</div>

    <!-- POC as hero -->
    <div class="poc-hero">
      <div class="poc-hero-label">Point of Control</div>
      <div class="poc-hero-value">${poc > 0 ? '$' + fmt(poc) : '—'}</div>
      <div class="poc-hero-migration" style="color:${pocColor}">
        ${pocArrow} ${esc(mig)}${deltaPts ? ' · ' + deltaPts : ''}
        ${pocSpeed ? '<span class="poc-speed">' + esc(pocSpeed) + (pocAccel === 'ACCELERATING' ? ' ↑↑' : pocAccel === 'DECELERATING' ? ' ↓' : '') + '</span>' : ''}
      </div>
      <div class="poc-hero-loc" style="color:${pvaColor}">${esc(locText)}</div>
    </div>

    <!-- Value area -->
    <div class="cmd-va-strip">
      <div class="va-chip va-chip-vah">VAH $${vah > 0 ? fmt(vah) : '—'}</div>
      <div class="va-chip va-chip-poc">POC $${poc > 0 ? fmt(poc) : '—'}</div>
      <div class="va-chip va-chip-val">VAL $${val_ > 0 ? fmt(val_) : '—'}</div>
    </div>

    <!-- Auction state -->
    <div class="cmd-auction-row">
      <div class="cmd-auction-state" style="color:${auctionColor}">${esc(auctionName)}</div>
      <div class="cmd-auction-meta">${esc(isInit ? 'Initiative' : isResp ? 'Responsive' : isTrend ? 'Trend Day' : 'Balanced')} · ${auctionConf}%</div>
    </div>

    <!-- Acceptance -->
    ${accStatus ? `<div class="cmd-acceptance-row">
      <span class="cmd-acc-label">Acceptance</span>
      <span class="cmd-acc-status" style="color:${accColor}">${esc(accStatus)} at ${esc(accLevel)}</span>
    </div>` : ''}

    <!-- Excess warning -->
    ${excess ? `<div class="cmd-excess-row">⚠ ${esc(excess)}</div>` : ''}

    <!-- ICI + price -->
    <div class="cmd-ici-row">
      <div class="cmd-ici-num" style="color:${iciColor}">${fmtI(ici)}<span class="cmd-ici-label">ICI</span></div>
      <div class="cmd-price-num">$${fmt(price)}<span class="cmd-price-label">SPX</span></div>
    </div>

    ${wouldTrade === false ? '<div class="cmd-no-trade-note">Institutional traders would not participate here</div>' : ''}
  `;
}


function renderAuctionPanel(d) {
  const el = $('auctionPanel');
  if (!el || !d) return;
  const ai  = d.auction_intelligence || {};
  const au  = d.auction || {};
  const ms  = d.market_state || {};
  const vp  = d.volume_profile || {};
  const lvl = vp.levels || {};
  const g   = d.gamma_regime || {};

  const poc    = ms.poc   || lvl.poc || au.poc  || 0;
  const vah    = ms.vah   || lvl.vah || au.vah  || 0;
  const val_   = ms.val   || lvl.val || au.val  || 0;
  const vwap   = ms.vwap  || 0;
  const price  = ms.price || 0;
  const mig    = ms.poc_migration || au.poc_migration || '--';
  const pvp    = ms.price_vs_poc  || '';
  const pva    = ms.price_vs_va   || '';

  const aiPocMig = ai.poc_migration  || {};
  const aiState  = ai.auction_state  || {};
  const aiAcc    = ai.acceptance     || {};
  const aiHvbo   = ai.hvbo           || {};
  const aiExcess = ai.excess         || {};

  // Auction verb — what are institutions doing?
  const auctionVerb =
    pva === 'ABOVE_VAH' && mig === 'RISING'  ? 'Accepting Higher'    :
    pva === 'ABOVE_VAH' && mig !== 'RISING'  ? 'Testing Higher'      :
    pva === 'BELOW_VAL' && mig === 'FALLING' ? 'Accepting Lower'     :
    pva === 'BELOW_VAL' && mig !== 'FALLING' ? 'Testing Lower'       :
    (aiAcc.primary_status === 'REJECTED')    ? 'Rejecting'           :
    mig === 'RISING'                          ? 'POC Rising'          :
    mig === 'FALLING'                         ? 'POC Falling'         :
    (aiState.is_balanced)                     ? 'Balanced Auction'    : 'Monitoring';

  const verbColor =
    auctionVerb.includes('Accepting Higher') || auctionVerb.includes('POC Rising') ? 'var(--green)' :
    auctionVerb.includes('Accepting Lower') || auctionVerb.includes('POC Falling') || auctionVerb.includes('Rejecting') ? 'var(--red)' :
    auctionVerb.includes('Testing') ? 'var(--amber)' : 'var(--muted)';

  // POC migration: show delta + narrative word
  const pocDelta = aiPocMig.delta || 0;
  const pocArrow = mig === 'RISING' ? '▲' : mig === 'FALLING' ? '▼' : '—';
  const pocColor = mig === 'RISING' ? 'var(--green)' : mig === 'FALLING' ? 'var(--red)' : 'var(--muted)';
  const pocDeltaStr = pocDelta !== 0 ? (pocDelta > 0 ? '+' : '') + pocDelta.toFixed(2) : '';
  const pocAccel = aiPocMig.acceleration || '';
  const auctionConf = aiState.confidence || (au.confidence) || 0;

  // Acceptance sub-text
  const accStatus  = aiAcc.primary_status || '';
  const accLevel   = aiAcc.primary_level  || '';
  const accNote    = aiAcc.primary_note   || au.narrative || '';
  const accColor   = accStatus === 'ACCEPTING' ? 'var(--green)' : accStatus === 'REJECTED' ? 'var(--red)' : 'var(--amber)';

  // Value width
  const valWidth = vah > 0 && val_ > 0 ? (vah - val_).toFixed(2) : null;

  // ── Auction Narrative 2.0 ──────────────────────────────────────────────────
  // Each condition answers three questions:
  //   1. What is price doing?  2. What is the auction doing?  3. What does it mean?
  const instNarrative = (() => {
    // ── Above value ──────────────────────────────────────────────────────────
    if (pva === 'ABOVE_VAH' && mig === 'RISING')
      return 'Price is above Value Area High and POC is migrating higher. ' +
             'Institutions are actively accepting these prices as fair value — ' +
             'this is a confirmed breakout. The auction is expanding upward with conviction.';
    if (pva === 'ABOVE_VAH' && mig === 'STABLE')
      return 'Price is above Value Area High, but POC has not yet migrated higher. ' +
             'The auction is pausing — institutions have not fully accepted these prices. ' +
             'Watch for POC to follow. If it stalls, this is a probe, not acceptance.';
    if (pva === 'ABOVE_VAH' && mig === 'FALLING')
      return 'Price is probing above VAH but POC is migrating lower. ' +
             'This is a divergence — sellers are distributing into the breakout attempt. ' +
             'High probability of a rejection and rotation back into value.';

    // ── Below value ──────────────────────────────────────────────────────────
    if (pva === 'BELOW_VAL' && mig === 'FALLING')
      return 'Price is below Value Area Low and POC is migrating lower. ' +
             'Institutions are accepting lower prices as fair value — ' +
             'this is a confirmed breakdown. The auction is expanding downward with conviction.';
    if (pva === 'BELOW_VAL' && mig === 'STABLE')
      return 'Price is testing below Value Area Low, but POC remains higher. ' +
             'Sellers are probing lower prices, but the auction has not accepted them yet. ' +
             'Responsive buyers may defend this level. Wait for POC to confirm before treating as a breakdown.';
    if (pva === 'BELOW_VAL' && mig === 'RISING')
      return 'Price is below Value Area Low, but POC is migrating higher — a significant divergence. ' +
             'Sellers are pushing lower while the auction center moves up. ' +
             'This is a failed breakdown setup. Buyers defending the low with increasing conviction.';

    // ── Inside value, rejection ───────────────────────────────────────────────
    if (accStatus === 'REJECTED' && pvp === 'ABOVE')
      return 'Price attempted to hold above POC but was rejected. ' +
             'Institutions are not accepting prices above the control point. ' +
             'Expect a rotation toward VAL unless buyers quickly reclaim POC.';
    if (accStatus === 'REJECTED' && pvp === 'BELOW')
      return 'Price attempted to hold below POC but was rejected. ' +
             'Sellers failed to push the auction lower from the control point. ' +
             'Responsive buyers are defending POC — watch for a bounce toward VAH.';
    if (accStatus === 'REJECTED')
      return 'Price was rejected at the reference level. ' +
             'Institutions are not accepting these prices. A rotation back toward POC is likely.';

    // ── Inside value, POC migrating ───────────────────────────────────────────
    if (pva === 'INSIDE' && pvp === 'ABOVE' && mig === 'RISING')
      return 'Price is above POC inside value with POC migrating higher. ' +
             'Buyers are building control from within the value area. ' +
             'A break of VAH with POC following would confirm initiative buying.';
    if (pva === 'INSIDE' && pvp === 'BELOW' && mig === 'FALLING')
      return 'Price is below POC inside value with POC migrating lower. ' +
             'Sellers are building control from within the value area. ' +
             'A break of VAL with POC following would confirm initiative selling.';
    if (mig === 'RISING')
      return 'POC is migrating higher — buyers are building a control zone. ' +
             'Institutional acceptance is increasing. A break of VAH confirms the bias.';
    if (mig === 'FALLING')
      return 'POC is migrating lower — sellers are building a control zone. ' +
             'Institutional distribution is increasing. A break of VAL confirms the bias.';

    // ── Reclaim scenarios ─────────────────────────────────────────────────────
    if (pvp === 'ABOVE' && accStatus === 'ACCEPTING' && pva === 'INSIDE')
      return 'Price is accepting above POC inside value. ' +
             'Buyers have reclaimed the control point — a constructive sign. ' +
             'A push toward VAH is the likely next reference level.';
    if (pvp === 'BELOW' && accStatus === 'ACCEPTING' && pva === 'INSIDE')
      return 'Price is accepting below POC inside value. ' +
             'Sellers have reclaimed the control point — a constructive bearish sign. ' +
             'A push toward VAL is the likely next reference level.';

    // ── Default: balanced ─────────────────────────────────────────────────────
    return 'Balanced auction — price is inside value with no clear directional commitment. ' +
           'The market is in equilibrium. Avoid new positions until the auction breaks ' +
           'above VAH or below VAL with POC confirming.';
  })();

  // ── Institutional bias phrase (for bottom of ladder) ──────────────────────
  // Captures the "split brain" situations (price going one way, auction another)
  const instBias = (() => {
    if (pva === 'ABOVE_VAH' && mig === 'RISING')  return { bull: 'Bullish price',  bear: null,           note: 'Confirmed acceptance higher' };
    if (pva === 'ABOVE_VAH' && mig === 'STABLE')  return { bull: 'Bullish price',  bear: 'Neutral auction', note: 'Probe — not yet accepted' };
    if (pva === 'ABOVE_VAH' && mig === 'FALLING') return { bull: 'Bullish price',  bear: 'Bearish auction', note: 'Divergence — rejection risk' };
    if (pva === 'BELOW_VAL' && mig === 'FALLING') return { bull: null,             bear: 'Bearish price',  note: 'Confirmed acceptance lower' };
    if (pva === 'BELOW_VAL' && mig === 'STABLE')  return { bull: 'Bullish auction',bear: 'Bearish price',  note: 'Lower probe — not accepted' };
    if (pva === 'BELOW_VAL' && mig === 'RISING')  return { bull: 'Bullish auction',bear: 'Bearish price',  note: 'Failed breakdown — watch reclaim' };
    if (mig === 'RISING')  return { bull: 'Bullish value', bear: null,            note: 'POC migrating higher' };
    if (mig === 'FALLING') return { bull: null,            bear: 'Bearish value', note: 'POC migrating lower' };
    return { bull: null, bear: null, note: 'Balanced — no bias' };
  })();

  el.innerHTML = `
    <div class="ap-auction-hero">
      <div class="ap-auction-verb" style="color:${verbColor}">${esc(auctionVerb)}</div>
      ${auctionConf > 0 ? `<div class="ap-auction-conf">Confidence <span style="color:${verbColor}">${auctionConf}%</span></div>` : ''}
    </div>

    <div class="ap-poc-row">
      <div class="ap-poc-main">
        <span class="ap-poc-arrow" style="color:${pocColor}">${pocArrow}</span>
        <span class="ap-poc-label">POC</span>
        <span class="ap-poc-val">$${poc > 0 ? fmt(poc) : '—'}</span>
      </div>
      ${pocDeltaStr ? `<div class="ap-poc-delta" style="color:${pocColor}">${pocDeltaStr} pts${pocAccel === 'ACCELERATING' ? ' ↑↑ accelerating' : pocAccel === 'DECELERATING' ? ' slowing' : ''}</div>` : ''}
    </div>

    <div class="ap-acceptance-block">
      <div class="ap-acc-status" style="color:${accColor}">${accStatus || '—'} ${accLevel ? 'at ' + esc(accLevel) : ''}</div>
    </div>

    <div class="ap-inst-narrative">${esc(instNarrative)}</div>
    ${instBias.note ? `<div class="ap-bias-strip">
      ${instBias.bull ? `<span class="ap-bias-bull">▲ ${esc(instBias.bull)}</span>` : ''}
      ${instBias.bear ? `<span class="ap-bias-bear">▼ ${esc(instBias.bear)}</span>` : ''}
      <span class="ap-bias-note">${esc(instBias.note)}</span>
    </div>` : ''}

    <div class="ap-va-strip">
      <div class="ap-va-item ap-va-vah"><span>VAH</span><b>$${fmt(vah)}</b></div>
      <div class="ap-va-item ap-va-vwap"><span>VWAP</span><b>$${fmt(vwap)}</b></div>
      <div class="ap-va-item ap-va-val"><span>VAL</span><b>$${fmt(val_)}</b></div>
    </div>

    ${valWidth ? `<div class="ap-va-width">Value width: <b>${valWidth} pts</b>${aiHvbo.value_rotation_pct ? ' · Rotation: '+aiHvbo.value_rotation_pct+'%' : ''}</div>` : ''}

    ${aiExcess.detected ? `<div class="ap-excess-inline">⚠ ${esc((aiExcess.type||'').replace(/_/g,' '))} — ${esc(aiExcess.action||'')}</div>` : ''}

    ${aiHvbo.available && aiHvbo.hvbo_low ? `
    <div class="ap-hvbo-row">
      <span class="ap-hvbo-label">HVBO</span>
      <span class="ap-hvbo-val">$${fmt(aiHvbo.hvbo_low)}–$${fmt(aiHvbo.hvbo_high)}</span>
      <span class="ap-hvbo-loc">${esc((aiHvbo.price_location||'').replace(/_/g,' '))}</span>
    </div>` : ''}
  `;
}


function renderCoachSnapshot(d) {
  const el = $('coachSnapshot');
  if (!el || !d) return;
  const coach = d.trade_coach || {};
  const risk  = d.risk || {};
  const ms    = d.market_state || {};
  const state = coach.state || d.decision_state || 'NO_TRADE';

  const isEnter = state.startsWith('ENTER');
  const isWatch = state.startsWith('WATCH') || state === 'READY';
  const badgeCls = isEnter ? 'db-green' : isWatch ? 'db-amber' : 'db-red';

  // Main action (3.1 prose)
  const action = coach.action || d.executive_summary || 'Waiting for institutional alignment.';

  // Trade levels
  const stop  = coach.stop  != null ? '$' + fmt(coach.stop)    : '--';
  const inv   = coach.invalidation != null ? '$' + fmt(coach.invalidation) : '--';
  const t1    = coach.target1 != null ? '$' + fmt(coach.target1) : '--';
  const t2    = coach.target2 != null ? '$' + fmt(coach.target2) : '--';
  const entry = coach.entry_zone || risk.entry_zone || '--';
  const contract = coach.contract_hint || risk.contract_hint || '--';

  // Scale plan
  const scalePlan = (coach.scale_out_plan || []);
  const scaleHtml = scalePlan.length
    ? `<div class="coach-scale-plan">${scalePlan.map(s => `<div class="scale-step">→ ${esc(s)}</div>`).join('')}</div>`
    : '';

  // Do-not-trade conditions
  const dontTrade = coach.dont_trade_if || [];
  const dontHtml = dontTrade.length
    ? `<div class="coach-dont-trade">
         <div class="dont-label">Do not enter if:</div>
         ${dontTrade.map(c => `<div class="dont-item">• ${esc(c)}</div>`).join('')}
       </div>`
    : '';

  // Checklist
  const checklist = coach.checklist || [];
  const checkHtml = checklist.length
    ? `<div class="coach-checklist">${checklist.map(c =>
        `<div class="check-item ${c.met ? 'check-met' : 'check-miss'}">
           <span class="check-icon">${c.met ? '✓' : '✗'}</span>
           <span class="check-label">${esc(c.label)}</span>
           ${c.note ? `<span class="check-note">${esc(c.note)}</span>` : ''}
         </div>`
      ).join('')}</div>`
    : '';

  // Structure context
  const poc  = coach.poc  || ms.poc;
  const vwap = coach.vwap || ms.vwap;
  const pvp  = coach.price_vs_poc || ms.price_vs_poc || '--';
  const pva  = coach.price_vs_va  || ms.price_vs_va  || '--';
  const mig  = coach.poc_migration || ms.poc_migration || '--';

  const readiness = coach.readiness != null ? coach.readiness : null;
  const readCls = readiness >= 80 ? 'ici-green' : readiness >= 60 ? 'ici-amber' : 'ici-red';

  el.innerHTML = `
    <div class="coach-action-block ${badgeCls}">${esc(action)}</div>

    <div class="coach-levels-grid">
      <div class="cl-item"><span class="cl-label">Contract</span><b class="cl-val">${esc(contract)}</b></div>
      <div class="cl-item"><span class="cl-label">Entry</span><b class="cl-val">${esc(entry)}</b></div>
      <div class="cl-item"><span class="cl-label">Stop</span><b class="cl-val rv-red">${stop}</b></div>
      <div class="cl-item"><span class="cl-label">Invalidation</span><b class="cl-val rv-red">${inv}</b></div>
      <div class="cl-item"><span class="cl-label">Target 1</span><b class="cl-val rv-green">${t1}</b></div>
      <div class="cl-item"><span class="cl-label">Target 2</span><b class="cl-val rv-green">${t2}</b></div>
      ${poc ? `<div class="cl-item"><span class="cl-label">POC</span><b class="cl-val">$${fmt(poc)}</b></div>` : ''}
      ${vwap ? `<div class="cl-item"><span class="cl-label">VWAP</span><b class="cl-val">$${fmt(vwap)}</b></div>` : ''}
    </div>

    ${readiness != null ? `
    <div class="coach-readiness">
      <span class="cr-label">Readiness</span>
      <span class="cr-bar-wrap"><span class="cr-bar" style="width:${readiness}%"></span></span>
      <span class="cr-num ${readCls}">${readiness}%</span>
    </div>` : ''}

    ${scaleHtml}
    ${dontHtml}
    ${checkHtml}
  `;
}

async function loadConfidenceTimeline() {
  const el = $('confidenceTimeline');
  if (!el) return;
  try {
    const r = await fetch('/api/confidence_timeline?ticker=' + activeTicker, { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    if (!data.ok) throw new Error(data.error || 'Timeline API error');
    confidenceLog = (data.points || []).map(p => ({
      ts: p.time || (p.time_et || '').slice(11,16),
      ici: Number(p.ici || 0),
      state: p.state || 'NO_TRADE',
      price: p.price,
      net_flow: p.net_flow,
      gamma_regime: p.gamma_regime,
      recommendation: p.recommendation
    }));
    renderConfidenceTimeline();
  } catch (e) {
    // Browser-local fallback keeps the UI useful even if the endpoint is unavailable.
    renderConfidenceTimeline('local');
  }
}

async function resetConfidenceTimeline() {
  const el = $('confidenceTimeline');
  try {
    const r = await fetch('/api/confidence_timeline/reset?ticker=' + activeTicker, { method: 'POST', cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    confidenceLog = [];
    if (el) el.textContent = 'Timeline reset. Waiting for next snapshot...';
  } catch (e) {
    if (el) el.textContent = 'Reset failed: ' + e.message;
  }
}

function renderConfidenceTimeline(mode='server') {
  const el = $('confidenceTimeline');
  if (!el) return;
  if (!confidenceLog.length) { el.textContent = 'Waiting for server snapshots...'; return; }
  el.innerHTML = confidenceLog.slice(-14).map(p => {
    const c = p.ici >= 70 ? 'var(--green)' : p.ici >= 50 ? 'var(--amber)' : 'var(--red)';
    const nf = p.net_flow != null ? ' · ' + (p.net_flow >= 0 ? '+' : '') + '$' + fmtM(p.net_flow) : '';
    const gr = p.gamma_regime ? ' · ' + p.gamma_regime : '';
    return `<div class="timeline-row"><span>${esc(p.ts)}</span><div class="timeline-bar"><div style="width:${Math.max(2, Math.min(100,p.ici))}%;background:${c}"></div></div><b style="color:${c}">${fmtI(p.ici)}%</b><em title="${esc((p.state||'').replace(/_/g,' ') + nf + gr)}">${esc((p.state||'NO_TRADE').replace(/_/g,' '))}</em></div>`;
  }).join('') + `<div class="timeline-source">${mode === 'local' ? 'Local fallback' : 'Server timeline'} · ${confidenceLog.length} snapshots</div>`;
}

/* ════════════════════════════════════════════════════════════════════════════
   SPRINT 6.0.4 — FLOW INTELLIGENCE 2.0, STORY ENGINE, REPLAY, REVIEW
   ════════════════════════════════════════════════════════════════════════════ */

/* ── Flow Intelligence 2.0 ────────────────────────────────────────────────── */
function renderFlow2(d) {
  const el = $('flow2Panel');
  if (!el || !d) return;
  const fi = d.flow_intelligence || d.flow || {};
  const score  = Number(fi.intelligence_score || fi.flow_score || 0);
  const scoreColor = score >= 65 ? 'var(--green)' : score <= 35 ? 'var(--red)' : 'var(--amber)';
  const momentum = (fi.flow_momentum || 'STABLE').replace(/_/g, ' ');

  // Divergence block
  let divHTML = '';
  if (fi.divergence_type) {
    const dir = (fi.divergence_direction || '').toUpperCase();
    const divCls = fi.divergence_type === 'A_PLUS' && dir === 'BEARISH' ? 'div-aplus-bear'
                 : fi.divergence_type === 'A_PLUS' && dir === 'BULLISH' ? 'div-aplus-bull' : 'div-b';
    const divLabel = (fi.divergence_type === 'A_PLUS' ? 'A+ ' : 'B ') + dir + ' DIVERGENCE';
    const secsRem  = Number(fi.divergence_seconds_remaining || 0);
    const totalTTL = 600; // 10-min divergence window
    const divPct   = secsRem > 0 ? Math.round(secsRem / totalTTL * 100) : 0;
    const fillColor = fi.divergence_type === 'A_PLUS' ? (dir === 'BEARISH' ? 'var(--red)' : 'var(--green)') : 'var(--amber)';
    divHTML = `<div class="divergence-alert ${divCls}">
      <div class="div-title">${esc(divLabel)}${fi.divergence_downgraded ? ' (downgraded A+→B)' : ''}</div>
      <div class="div-desc">${esc(fi.divergence_description || '')}</div>
      ${secsRem > 0 ? `<div class="div-timer" style="color:${fillColor}">${secsRem}s remaining</div>
      <div class="div-bar"><div class="div-fill" style="width:${divPct}%;background:${fillColor}"></div></div>` : ''}
    </div>`;
  }

  // Absorption block
  let absHTML = '';
  if (fi.absorption) {
    absHTML = `<div class="absorption-block">
      <div class="ab-title">⚡ ABSORPTION CONFIRMED</div>
      <div class="ab-desc">${esc(fi.absorption_description || '')}</div>
    </div>`;
  }

  // Metrics grid
  const metrics = [
    { label: 'Flow Score',    val: fmtI(fi.flow_score),          sub: 'Options flow', color: clr(fi.flow_score,65,35) },
    { label: 'Order Flow',    val: fmtI(fi.order_flow_score),    sub: 'Sweep quality', color: clr(fi.order_flow_score,65,35) },
    { label: 'Net Premium',   val: '$' + fmtM(fi.net_premium),  sub: 'Call vs Put', color: (fi.net_premium||0) >= 0 ? 'var(--green)' : 'var(--red)' },
    { label: 'Call Premium',  val: '$' + fmtM(fi.call_premium), sub: fi.bias || '--', color: 'var(--green)' },
    { label: 'Put Premium',   val: '$' + fmtM(fi.put_premium),  sub: 'Defensive', color: 'var(--red)' },
    { label: 'Sweep Count',   val: fmtI(fi.sweep_count),         sub: fi.sweep_aggression || '--', color: fi.sweep_count >= 6 ? 'var(--amber)' : 'var(--muted)' },
  ];
  const metricsHTML = metrics.map(m =>
    `<div class="fm-card">
      <div class="fm-label">${m.label}</div>
      <div class="fm-val" style="color:${m.color}">${m.val}</div>
      <div class="fm-sub">${m.sub}</div>
    </div>`
  ).join('');

  // Momentum rows
  const momentumRows = [
    { label: 'Bias',         val: fi.bias || '--', badge: fi.bias },
    { label: 'Momentum',     val: momentum },
    { label: 'Flow Delta',   val: fi.flow_delta != null ? (fi.flow_delta > 0 ? '+' : '') + fi.flow_delta : '--' },
    { label: 'Prev Score',   val: fi.prev_flow_score != null ? fi.prev_flow_score : '--' },
    { label: 'Block Conv.',  val: fi.block_conviction || '--' },
    { label: 'At Gamma Lvl',  val: fi.at_gamma_level ? 'YES' : 'NO' },
    { label: 'Session High',  val: fi.session_high ? '$' + fmt(fi.session_high) : '--' },
    { label: 'Session Low',   val: fi.session_low  ? '$' + fmt(fi.session_low)  : '--' },
    { label: 'Rolling High',  val: fi.rolling_high ? '$' + fmt(fi.rolling_high) : '--' },
    { label: 'Gate Override', val: fi.gate_override ? fi.gate_override.replace(/_/g,' ') : 'NONE' },
  ];
  const momHTML = momentumRows.map(r => {
    const bCls = r.badge === 'BULLISH' ? 'ev-bull' : r.badge === 'BEARISH' ? 'ev-bear' : '';
    return `<div class="momentum-row">
      <span class="mr-label">${r.label}</span>
      <span class="mr-val ${bCls ? 'mr-badge ' + bCls : ''}">${esc(String(r.val || '--'))}</span>
    </div>`;
  }).join('');

  // Notes
  const notes = (fi.notes || []).slice(0, 8);
  const notesHTML = notes.length
    ? `<div style="margin-top:10px">${notes.map(n => `<div class="replay-event"><span class="re-dot" style="background:var(--amber)"></span><div class="re-text">${esc(n)}</div></div>`).join('')}</div>`
    : '';

  el.innerHTML = `
    <div class="flow-score-ring">
      <div class="flow-ring-num" style="color:${scoreColor}">${fmtI(score)}</div>
      <div class="flow-ring-meta">
        <div class="flow-ring-label">Intelligence Score</div>
        <div class="flow-ring-sub">${momentum} · ${fi.flow_recommendation ? fi.flow_recommendation.replace(/_/g,' ') : '--'}</div>
        <div style="height:5px;background:var(--bdr);border-radius:3px;overflow:hidden;margin-top:8px;width:180px">
          <div style="height:100%;border-radius:3px;width:${score}%;background:${scoreColor};transition:width .5s"></div>
        </div>
      </div>
    </div>
    ${divHTML}${absHTML}
    <div class="flow-metrics-grid">${metricsHTML}</div>
    <div>${momHTML}</div>
    ${notesHTML}
  `;
}

/* ── Story Engine ─────────────────────────────────────────────────────────── */
function _renderChapterList(chapters, containerId) {
  const el = $(containerId);
  if (!el) return;
  if (!chapters || !chapters.length) {
    el.innerHTML = '<div style="color:var(--faint);font-size:11px;padding:8px">No chapters yet.</div>';
    return;
  }
  el.innerHTML = chapters.map((c, i) => `
    <div class="story-entry">
      <div class="story-connector">
        <div class="s-dot" style="background:${esc(c.color || 'var(--faint)')}"></div>
        ${i < chapters.length - 1 ? '<div class="s-line"></div>' : ''}
      </div>
      <div class="story-body">
        <div class="story-chapter" style="color:${esc(c.color || 'var(--muted)')}">${esc(c.chapter || 'Chapter')}</div>
        <div class="story-text">${esc(c.text || '')}</div>
        <div class="story-time">${esc(c.time || '--')}</div>
      </div>
    </div>`).join('');
}

function renderStory(d) {
  if (!d) return;
  const story = d.story || {};

  // Executive summary
  const summEl = $('execSummary');
  if (summEl) summEl.textContent = d.executive_summary || story.executive_summary || '--';

  // Meta line
  const metaEl = $('storyMeta');
  if (metaEl) {
    const parts = [story.engine, story.generated_at,
      story.has_auction_chapter ? '● Auction' : '',
      story.has_tape_chapter    ? '● Tape'    : ''].filter(Boolean);
    metaEl.innerHTML = parts.map(s => `<span>${esc(s)}</span>`).join('');
  }

  // Knows / Recommends split
  _renderChapterList(story.knows_chapters     || story.chapters || [], 'storyKnows');
  _renderChapterList(story.recommends_chapters || [],                   'storyRecommends');

  // Full narrative
  const narr = $('narrativeBlock');
  if (narr && story.full_narrative) narr.textContent = story.full_narrative;
}

/* ── Replay ───────────────────────────────────────────────────────────────── */
function captureReplaySnap(d) {
  if (!d) return;
  const _ai  = d.auction_intelligence || {};
  const _ms  = d.market_state || {};
  const snap = {
    ts:      new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true, timeZone: 'America/New_York' }),
    state:   d.decision_state || '--',
    ici:     Number((d.ici || {}).ici || 0),
    price:   _ms.price || (d.ribbon || {}).spx_price || null,
    exec:    (d.execution || {}).execution_state || '--',
    flow:    (d.flow_intelligence || {}).flow_momentum || '--',
    notes:   ((d.flow_intelligence || {}).notes || []).slice(0, 2),
    summary: d.executive_summary || '',
    // Auction context for timeline
    poc:           _ms.poc || 0,
    poc_migration: _ms.poc_migration || '',
    auction_state: ((_ai.auction_state || {}).state || (d.auction || {}).auction_state || '').replace(/_/g,' '),
    acceptance:    ((_ai.acceptance || {}).primary_status || ''),
    acc_level:     ((_ai.acceptance || {}).primary_level  || ''),
    excess:        ((_ai.excess || {}).detected ? (_ai.excess.type||'').replace(/_/g,' ') : ''),
    tape_bias:     _ms.tape_bias || '',
    pine_state:    _ms.pine_state || '',
  };
  replaySnaps.push(snap);
  if (replaySnaps.length > 120) replaySnaps.shift(); // keep last 120 snaps (~24 min at 12s)
  renderReplayList();
  const scrub = $('replayScrub');
  if (scrub) { scrub.max = replaySnaps.length - 1; if (!replayPlaying) scrub.value = replaySnaps.length - 1; }
}

function renderReplayList() {
  const el = $('replayEvents');
  if (!el) return;
  if (!replaySnaps.length) { el.innerHTML = '<div style="color:var(--faint);font-size:12px;padding:12px">No replay data yet. Data is captured every 12 seconds.</div>'; return; }
  el.innerHTML = [...replaySnaps].reverse().slice(0, 30).map(s => {
    const decColor = s.state.includes('CALL') ? 'var(--green)' : s.state.includes('PUT') ? 'var(--red)' : s.state.includes('WATCH') || s.state === 'READY' ? 'var(--amber)' : 'var(--muted)';
    const iciColor = s.ici >= 70 ? 'var(--green)' : s.ici >= 50 ? 'var(--amber)' : 'var(--red)';
    return `<div class="replay-event">
      <span class="re-time">${s.ts}</span>
      <div class="re-dot" style="background:${decColor}"></div>
      <div class="re-text">
        <b style="color:${decColor}">${s.state.replace(/_/g,' ')}</b> · ICI <b style="color:${iciColor}">${fmtI(s.ici)}</b>${s.price ? ' · $' + fmt(s.price) : ''} · ${s.flow.replace(/_/g,' ')}
        ${s.notes.map(n => `<br><span style="color:var(--faint)">→ ${esc(n)}</span>`).join('')}
      </div>
    </div>`;
  }).join('');
}

function renderReplayFrame(idx) {
  const snap = replaySnaps[idx];
  const el   = $('replayFrame');
  if (!el || !snap) return;
  const decColor = snap.state.includes('CALL') ? 'var(--green)' : snap.state.includes('PUT') ? 'var(--red)' : snap.state.includes('WATCH') || snap.state === 'READY' ? 'var(--amber)' : 'var(--muted)';
  el.innerHTML = `
    <div class="rf-label">Replay — ${snap.ts}</div>
    <div style="display:flex;gap:14px;align-items:center;margin-bottom:8px;flex-wrap:wrap">
      <div style="font-family:var(--mono);font-size:22px;font-weight:900;color:${decColor}">${snap.state.replace(/_/g,' ')}</div>
      <div style="font-family:var(--mono);font-size:18px;color:${snap.ici >= 70 ? 'var(--green)' : snap.ici >= 50 ? 'var(--amber)' : 'var(--red)'}">ICI ${fmtI(snap.ici)}</div>
      ${snap.price ? `<div style="font-family:var(--mono);font-size:15px;color:var(--blue)">$${fmt(snap.price)}</div>` : ''}
      <div style="font-size:11px;color:var(--muted)">${snap.exec.replace(/_/g,' ')}</div>
    </div>
    ${snap.summary ? `<div class="rf-note">${esc(snap.summary)}</div>` : ''}
    ${snap.notes.map(n => `<div class="rf-note" style="margin-top:4px;font-size:10px;color:var(--faint)">· ${esc(n)}</div>`).join('')}
  `;
  const timeEl = $('replayTime'); if (timeEl) timeEl.textContent = (idx + 1) + ' / ' + replaySnaps.length;
}

function initReplayControls() {
  const scrub = $('replayScrub');
  if (scrub) {
    scrub.addEventListener('input', () => {
      replayIdx = parseInt(scrub.value);
      renderReplayFrame(replayIdx);
    });
  }
  const prevBtn = $('repPrev');
  const nextBtn = $('repNext');
  const liveBtn = $('repLive');
  if (prevBtn) prevBtn.addEventListener('click', () => { if (replayIdx > 0) { replayIdx--; if (scrub) scrub.value = replayIdx; renderReplayFrame(replayIdx); } });
  if (nextBtn) nextBtn.addEventListener('click', () => { if (replayIdx < replaySnaps.length - 1) { replayIdx++; if (scrub) scrub.value = replayIdx; renderReplayFrame(replayIdx); } });
  if (liveBtn) liveBtn.addEventListener('click', () => { replayIdx = replaySnaps.length - 1; if (scrub) scrub.value = replayIdx; renderReplayFrame(replayIdx); });
}

/* ── Review ───────────────────────────────────────────────────────────────── */
function addReviewEntry(d) {
  if (!d) return;
  const state = d.decision_state || '--';
  if (!['ENTER_CALL','ENTER_PUT','READY','WATCH_CALLS','WATCH_PUTS'].includes(state)) return;

  const coach   = d.trade_coach || {};
  const risk    = d.risk || {};
  const ms      = d.market_state || {};
  const ici_obj = d.ici || {};
  const exec    = d.execution || {};

  reviewLog.unshift({
    ts:           new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true, timeZone: 'America/New_York' }),
    ticker:       activeTicker,
    state,
    ici:          Number(ici_obj.ici || 0),
    grade:        d.grade || '',
    // Contract / strike
    contract:     coach.contract_hint || risk.contract_hint || '',
    approved_side: coach.approved_side || '',
    // Trade levels
    entry_zone:   coach.entry_zone   || risk.entry_zone   || '',
    stop:         coach.stop         != null ? coach.stop         : (risk.stop         != null ? risk.stop         : null),
    invalidation: coach.invalidation != null ? coach.invalidation : null,
    target1:      coach.target1      != null ? coach.target1      : (risk.target1      != null ? risk.target1      : null),
    target2:      coach.target2      != null ? coach.target2      : (risk.target2      != null ? risk.target2      : null),
    // Market context at time of signal
    poc:          ms.poc   || '',
    vwap:         ms.vwap  || '',
    pine_state:   ms.pine_state || exec.execution_state || '',
    signal_secs:  ms.signal_secs || 0,
    tape_bias:    ms.tape_bias || '',
    flow_bias:    ms.flow_bias || '',
    // Narrative
    coach_action: coach.action || '',
    summary:      d.executive_summary || '',
    // Checklist readiness
    readiness:    coach.readiness != null ? coach.readiness : null,
    blockers:     coach.blockers || [],
  });
  if (reviewLog.length > 60) reviewLog.pop();
  renderReview();
}

function renderReview() {
  const el = $('reviewPanel');
  if (!el) return;
  if (!reviewLog.length) {
    el.innerHTML = `<div class="review-empty">
      No signals logged yet this session.<br>
      <span style="font-size:10px;color:var(--faint)">ENTER_CALL, ENTER_PUT, READY, and WATCH states are captured automatically on each refresh cycle.</span>
    </div>`;
    return;
  }

  el.innerHTML = reviewLog.map((r, idx) => {
    const isCall    = r.state.includes('CALL') || r.approved_side === 'CALL';
    const isPut     = r.state.includes('PUT')  || r.approved_side === 'PUT';
    const isEnter   = r.state.startsWith('ENTER');
    const isWatch   = r.state.startsWith('WATCH') || r.state === 'READY';
    const stateColor= isEnter ? 'var(--green)' : isWatch ? 'var(--amber)' : 'var(--muted)';
    const sideColor = isCall ? 'var(--green)' : isPut ? 'var(--red)' : 'var(--muted)';

    // Format stop/target values
    const fmtLevel = v => v != null && v !== '' ? `$${fmt(Number(v))}` : '--';

    // Pine signal remaining
    const pineStr = r.pine_state === 'CONFIRMED' && r.signal_secs > 0
      ? `Pine confirmed (${Math.floor(r.signal_secs/60)}m${r.signal_secs%60}s)`
      : r.pine_state === 'CONFIRMED' ? 'Pine confirmed' : 'Waiting for Pine';

    // Blockers
    const blockerHtml = r.blockers?.length
      ? `<div class="sl-blockers">${r.blockers.slice(0,3).map(b => `<span>• ${esc(b)}</span>`).join('')}</div>`
      : '';

    // Readiness bar
    const readHtml = r.readiness != null
      ? `<div class="sl-readiness">
           <span class="sl-read-label">Readiness</span>
           <div class="sl-read-bar"><div style="width:${r.readiness}%;background:${r.readiness>=80?'var(--green)':r.readiness>=60?'var(--blue)':'var(--amber)'}"></div></div>
           <span class="sl-read-num">${r.readiness}%</span>
         </div>`
      : '';

    return `<div class="signal-log-entry ${isEnter ? 'sle-enter' : isWatch ? 'sle-watch' : ''}">
      <div class="sle-header">
        <div class="sle-time">${esc(r.ts)}</div>
        <div class="sle-state" style="color:${stateColor}">${esc(r.state.replace(/_/g,' '))}</div>
        <div class="sle-grade">${esc(r.grade)}</div>
        <div class="sle-ici">ICI ${fmtI(r.ici)}</div>
      </div>

      ${r.contract ? `<div class="sle-contract" style="color:${sideColor}">${esc(r.contract)}</div>` : ''}

      <div class="sle-levels">
        <div class="sle-level">
          <span class="sll-label">Entry</span>
          <span class="sll-val rv-blue">${esc(r.entry_zone || '--')}</span>
        </div>
        <div class="sle-level">
          <span class="sll-label">Stop</span>
          <span class="sll-val rv-red">${fmtLevel(r.stop)}</span>
        </div>
        <div class="sle-level">
          <span class="sll-label">Invalidation</span>
          <span class="sll-val rv-red">${fmtLevel(r.invalidation)}</span>
        </div>
        <div class="sle-level">
          <span class="sll-label">T1</span>
          <span class="sll-val rv-green">${fmtLevel(r.target1)}</span>
        </div>
        <div class="sle-level">
          <span class="sll-label">T2</span>
          <span class="sll-val rv-green">${fmtLevel(r.target2)}</span>
        </div>
        <div class="sle-level">
          <span class="sll-label">POC</span>
          <span class="sll-val">${r.poc ? '$'+fmt(r.poc) : '--'}</span>
        </div>
        <div class="sle-level">
          <span class="sll-label">VWAP</span>
          <span class="sll-val">${r.vwap ? '$'+fmt(r.vwap) : '--'}</span>
        </div>
        <div class="sle-level">
          <span class="sll-label">Pine</span>
          <span class="sll-val" style="color:${r.pine_state==='CONFIRMED'?'var(--green)':'var(--faint)'}">${esc(pineStr)}</span>
        </div>
      </div>

      ${readHtml}
      ${r.coach_action ? `<div class="sle-action">${esc(r.coach_action)}</div>` : ''}
      ${blockerHtml}
    </div>`;
  }).join('');
}


/* ── Scanner Ideas + Manual Scan ──────────────────────────────────────────── */
function setScanStatus(text, tone = 'muted') {
  const el = $('scanStatusText');
  if (!el) return;
  el.textContent = text || '';
  el.className = 'scan-status scan-' + tone;
}

function setScanButtons(disabled) {
  const b = $('runScanBtn');
  if (b) {
    b.disabled = !!disabled;
    b.classList.toggle('is-loading', !!disabled);
    b.textContent = disabled ? 'Scanning...' : '▶ Run Scan';
  }
}

function renderScannerIdeas(payload) {
  const el = $('scannerIdeasPanel');
  if (!el) return;
  if (!payload || payload.ok === false) {
    el.innerHTML = `<div class="scanner-empty scanner-error">Scanner data unavailable${payload && payload.error ? ': ' + esc(payload.error) : ''}</div>`;
    return;
  }
  const ideas = Array.isArray(payload.ideas) ? payload.ideas : [];
  const count = payload.idea_count != null ? payload.idea_count : ideas.length;
  const status = payload.last_scan_status || 'Scanner status unavailable';
  const updated = payload.updated_at_et || '--';
  const inProgress = !!payload.scan_in_progress;
  setScanStatus(inProgress ? 'Scan running...' : `${count} qualified ideas`, inProgress ? 'busy' : (count > 0 ? 'good' : 'muted'));
  const summary = `
    <div class="scanner-summary">
      <span class="scanner-pill ${inProgress ? 'scanner-busy' : 'scanner-ok'}">${inProgress ? 'RUNNING' : 'READY'}</span>
      <span>${esc(status)}</span>
      <span>Ideas: ${count}</span>
      <span>Updated: ${esc(updated)}</span>
    </div>`;
  if (!ideas.length) {
    el.innerHTML = summary + `<div class="scanner-empty">No qualified scanner ideas are currently available. Run a scan or wait for the background scanner to finish.</div>`;
    return;
  }
  const rows = ideas.slice(0, 30).map(idea => {
    const side = (idea.direction || idea.side || idea.approved_side || '').toUpperCase();
    const isPut = side.includes('PUT');
    const isCall = side.includes('CALL');
    const sideCls = isCall ? 'scan-side-call' : isPut ? 'scan-side-put' : 'scan-side-watch';
    const ticker = idea.ticker || '--';
    const grade = idea.grade || idea.alert_tier || '--';
    const score = idea.final_score ?? idea.conviction_score ?? idea.score ?? idea.breakout_probability;
    const price = idea.price ?? idea.stock_price ?? idea.spot_price;
    const flowScore = idea.flow_score_directional ?? idea.flow_score ?? idea.order_flow_score_directional;
    const action = idea.status || idea.trade_permission || idea.breakout_probability_label || '';
    const contract = idea.option_contract || idea.recommended_contract || idea.contract_hint || '';
    return `<tr>
      <td><b>${esc(ticker)}</b></td>
      <td><span class="scan-side ${sideCls}">${esc(side || 'WATCH')}</span></td>
      <td>${esc(grade)}</td>
      <td>${score != null ? Number(score).toFixed(1) : '--'}</td>
      <td>${flowScore != null ? Number(flowScore).toFixed(1) : '--'}</td>
      <td>${price != null ? '$' + fmt(price) : '--'}</td>
      <td>${esc(action || '--')}</td>
      <td class="scan-contract-cell">${esc(contract || '--')}</td>
    </tr>`;
  }).join('');
  el.innerHTML = summary + `
    <div class="scanner-table-wrap">
      <table class="scanner-table">
        <thead><tr><th>Ticker</th><th>Side</th><th>Grade</th><th>Score</th><th>Flow</th><th>Price</th><th>Status</th><th>Contract</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}


async function loadScannerIdeas() {
  try {
    const r = await fetch('/api/scanner_ideas', { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    renderScannerIdeas(data);
    return data;
  } catch (e) {
    const el = $('scannerIdeasPanel');
    if (el) el.innerHTML = `<div class="scanner-empty scanner-error">Scanner ideas failed to load: ${esc(e.message)}</div>`;
    setScanStatus('Scanner load failed', 'bad');
    return null;
  }
}

async function runManualScan() {
  setScanButtons(true);
  setScanStatus('Starting scan...', 'busy');
  try {
    const r = await fetch('/api/run', { method: 'POST', cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    const ideas = data.ideas != null ? data.ideas : 0;
    setScanStatus(data.ok ? `Scan complete · ${ideas} ideas` : (data.status || 'Scan already running'), data.ok ? 'good' : 'busy');
    await loadScannerIdeas();
    await loadOS();
  } catch (e) {
    setScanStatus('Scan failed: ' + e.message, 'bad');
  } finally {
    setScanButtons(false);
  }
}

function initRunScanButtons() {
  const scanBtn = $('runScanBtn');
  if (scanBtn) scanBtn.addEventListener('click', runManualScan);
  const refreshScanner = $('refreshScannerBtn');
  if (refreshScanner) refreshScanner.addEventListener('click', loadScannerIdeas);
  const resetTimeline = $('resetTimelineBtn');
  if (resetTimeline) resetTimeline.addEventListener('click', resetConfidenceTimeline);
}

/* ════════════════════════════════════════════════════════════════════════════
   MASTER LOAD
   ════════════════════════════════════════════════════════════════════════════ */

/* ── Fix 4: AbortController timeout + Fix 6: heatmap=0 default ────────────
   fetchInstitutionalOS():
     - 6-second hard timeout via AbortController
     - heatmap=0 by default (loaded lazily by its own panel)
     - Returns stale osData on timeout rather than throwing
     - Shows "Engines warming up" if no stale data available
   ──────────────────────────────────────────────────────────────────────── */
async function fetchInstitutionalOS() {
  // Fix 6: heatmap=0 — heatmap loads in its own lazy panel
  const url = '/api/institutional_os?ticker=' + encodeURIComponent(activeTicker) + '&heatmap=0';
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 6000);   // Fix 4: 6s hard timeout

  try {
    const r = await fetch(url, { cache: 'no-store', signal: controller.signal });
    clearTimeout(timer);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    if (!data.ok) throw new Error(data.error || 'API error');
    return { data, timedOut: false, stale: !!data.stale };
  } catch (err) {
    clearTimeout(timer);
    const wasTimeout = err.name === 'AbortError';
    if (wasTimeout) console.warn('[APEX] /api/institutional_os timed out after 6s');
    else            console.warn('[APEX] /api/institutional_os failed:', err.message);
    // Fix 4: return stale data if available, otherwise signal warming-up state
    if (osData) return { data: osData, timedOut: wasTimeout, stale: true };
    return { data: null, timedOut: wasTimeout, stale: false };
  }
}

async function loadOS() {
  // Fix 5: prevent overlapping refreshes
  if (osLoading) { console.log('[APEX] loadOS skipped — already running'); return; }
  osLoading = true;
  const errEl = $('osError');
  try {
    const apiResult = await fetchInstitutionalOS();
    const data = apiResult.data;

    // Fix 4: handle timeout / warm-up — never leave UI on LOADING forever
    if (!data) {
      if (errEl) {
        errEl.style.display = '';
        errEl.textContent = apiResult.timedOut
          ? '⌛ Engines warming up — retrying in 5 seconds…'
          : '⚠ No data yet — retrying in 5 seconds…';
      }
      if (osData) await _renderAll(osData);   // render stale data if available
      setTimeout(loadOS, 5000);
      return;
    }

    osData = data;

    // Banner: stale vs fresh
    if (errEl) {
      if (apiResult.stale || data.stale) {
        errEl.style.display = '';
        errEl.textContent = '⟳ Showing cached data — refresh in progress';
      } else {
        errEl.style.display = 'none';
        errEl.textContent = '';
      }
    }

    await _renderAll(data);

    const lu = $('lastUpdated');
    if (lu) {
      const ms  = data.response_ms ? ' (' + data.response_ms + 'ms)' : '';
      const par = data.partial ? ' ⚡partial' : '';
      lu.textContent = 'Updated: ' + (data.updated_at_et || new Date().toLocaleTimeString()) + ms + par;
    }
  } catch (e) {
    if (errEl) { errEl.style.display = ''; errEl.textContent = '⚠ Dashboard error: ' + e.message; }
    console.error('[APEX] loadOS failed', e);
  } finally {
    osLoading = false;   // Fix 5: always release lock
  }
}

/* _renderAll — render all panels from a data object (fresh or stale) */
async function _renderAll(data) {
  const _r  = (fn, d) => { try { fn(d); } catch(e) { console.warn('Render error in ' + fn.name + ':', e.message); } };
  const _ra = async (fn) => { try { await fn(); } catch(e) { console.warn('Async render error:', e.message); } };
  try {
    // 6.0.3 panels
    _r(renderRibbon, data);
    _r(renderICI, data);
    _r(renderDecision, data);
    _r(renderTradeCoach, data);
    _r(renderEngineMatrix, data);
    _r(renderSession, data);
    _r(renderHeatmap, data);
    _r(recordConfidencePoint, data);
    _r(renderCommandCenter, data);
    _r(renderAuctionPanel, data);
    _r(renderCoachSnapshot, data);
    await _ra(loadConfidenceTimeline);

    // 6.0.4 panels
    _r(renderFlow2, data);
    _r(renderStory, data);
    _r(renderOvernightGamePlan, data);
    _r(renderExecutiveSummary, data);
    _r(renderOpFlow, data);
    _r(renderAuctionIntel, data);
    _r(renderDecisionTree, data);
    _r(captureTimelineEvent, data);
    _r(renderAuctionLadder, data);
    _r(renderDealerPanel, data);
    _r(renderPlaybook, data);
    _r(renderInstitutionalIntelligence, data);

    // Sprint 8 — Decision Command Center + new panels
    _r(renderDCC, data);
    _r(renderMarketDriversPanel, data);
    _r(renderStrikeMagnetPanel, data);
    _r(renderFlowMeter, data);
    _r(renderEIE, data);

    // Sprint 9 — Professional Workspace
    _r(renderWorkspace, data);

    if (data.market_status) _r(renderMarketStatusBanner, data.market_status);

    _r(captureReplaySnap, data);
    _r(addReviewEntry, data);

    // Fix 7: loadFlowTape() has its own setInterval — do NOT call here
  } catch (e) {
    console.warn('[APEX] _renderAll error:', e.message);
  }
}

/* ════════════════════════════════════════════════════════════════════════════
   SIGNAL LOG — Pine webhook signal history with outcome tracking
   ════════════════════════════════════════════════════════════════════════════ */

async function loadSignalLog() {
  const el = $('signalLogPanel');
  if (!el) return;
  try {
    const r = await fetch('/api/signal_log', { cache: 'no-store' });
    if (!r.ok) return;
    const data = await r.json();
    if (!data.ok || !data.signals?.length) {
      el.innerHTML = '<div class="review-empty">No Pine signals received yet this session.<br><span style="font-size:10px;color:var(--faint)">Signals arrive here from TradingView via the /tv_signal webhook.</span></div>';
      return;
    }
    el.innerHTML = data.signals.map(s => {
      const side = s.signal || s.side || '';
      const sc = side.includes('CALL') ? 'var(--green)' : side.includes('PUT') ? 'var(--red)' : 'var(--muted)';
      const outcome = s.outcome;
      const oc = outcome === 'WIN' ? 'var(--green)' : outcome === 'LOSS' ? 'var(--red)' : outcome === 'SCRATCH' ? 'var(--amber)' : 'var(--faint)';
      return `<div class="signal-log-entry ${side.includes('CALL') ? 'sle-enter' : side.includes('PUT') ? 'sle-enter' : ''}">
        <div class="sle-header">
          <div class="sle-time">${esc(s.bar_time || s.received_at_et?.slice(11,16) || '--')}</div>
          <div class="sle-state" style="color:${sc}">▶ ${esc(side)}</div>
          <div class="sle-ici">ICI ${fmtI(Number(s.apex_ici||0))}</div>
          ${outcome ? `<div class="sle-grade" style="color:${oc}">${esc(outcome)}${s.outcome_pnl!=null?' · '+(s.outcome_pnl>=0?'+':'')+s.outcome_pnl:''}</div>` : `<span style="font-size:9px;color:var(--faint)">Pending</span>`}
        </div>
        <div class="sle-contract" style="color:${sc}">${esc(s.ticker||'SPX')} ${esc(side)}</div>
        <div class="sle-levels">
          <div class="sle-level"><span class="sll-label">Price</span><span class="sll-val rv-blue">$${fmt(Number(s.price||0))}</span></div>
          <div class="sle-level"><span class="sll-label">Auction</span><span class="sll-val" style="font-size:9px">${esc((s.apex_auction||'--').replace(/_/g,' '))}</span></div>
          <div class="sle-level"><span class="sll-label">POC Mig</span><span class="sll-val">${esc(s.apex_poc_migration||'--')}</span></div>
          <div class="sle-level"><span class="sll-label">Accept</span><span class="sll-val">${esc(s.apex_acceptance||'--')}</span></div>
          <div class="sle-level"><span class="sll-label">POC</span><span class="sll-val">$${fmt(Number(s.poc||0))}</span></div>
          <div class="sle-level"><span class="sll-label">VWAP</span><span class="sll-val">$${fmt(Number(s.vwap||0))}</span></div>
          <div class="sle-level"><span class="sll-label">Internals</span><span class="sll-val">${s.intern_score||'--'}/3</span></div>
          <div class="sle-level"><span class="sll-label">Signal #</span><span class="sll-val">${s.signal_num||'--'}</span></div>
        </div>
        ${outcome ? '' : `<div style="margin-top:6px;display:flex;gap:5px">
          <button class="btn btn-ghost btn-mini" onclick="markOutcome('${esc(s.received_at)}','WIN')">WIN</button>
          <button class="btn btn-ghost btn-mini" onclick="markOutcome('${esc(s.received_at)}','LOSS')">LOSS</button>
          <button class="btn btn-ghost btn-mini" onclick="markOutcome('${esc(s.received_at)}','SCRATCH')">SCRATCH</button>
        </div>`}
      </div>`;
    }).join('');
  } catch(_) {}
}

async function markOutcome(receivedAt, outcome) {
  try {
    await fetch('/api/signal_outcome', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ received_at: receivedAt, outcome })
    });
    loadSignalLog();
  } catch(_) {}
}

async function loadSavedReviews() {
  const el = $('savedReviewsPanel');
  if (!el) return;
  try {
    const r = await fetch('/api/review/trades?ticker=' + activeTicker + '&limit=30', { cache: 'no-store' });
    if (!r.ok) return;
    const data = await r.json();
    if (!data.ok || !data.trades?.length) {
      el.innerHTML = '<div class="review-empty">No saved reviews yet. Use the form above to log completed trades.</div>';
      return;
    }
    el.innerHTML = `<div class="saved-reviews-table-wrap"><table class="scanner-table" style="min-width:700px">
      <thead><tr>
        <th>Ticker</th><th>Side</th><th>Contract</th>
        <th>Entry</th><th>Exit</th><th>Entry $</th><th>Exit $</th>
        <th>P&amp;L</th><th>Plan</th><th>Reason In</th>
      </tr></thead>
      <tbody>${data.trades.map(t => {
        const pnlCls = (t.pnl || 0) >= 0 ? 'rv-green' : 'rv-red';
        const sideCls = t.side === 'CALL' ? 'scan-side-call' : 'scan-side-put';
        return `<tr>
          <td><b>${esc(t.ticker || '')}</b></td>
          <td><span class="scan-side ${sideCls}">${esc(t.side || '')}</span></td>
          <td class="scan-contract-cell">${esc(t.contract || '--')}</td>
          <td style="font-family:var(--mono)">${esc(t.entry_time || '--')}</td>
          <td style="font-family:var(--mono)">${esc(t.exit_time  || '--')}</td>
          <td style="font-family:var(--mono)">${t.entry_price != null ? '$'+t.entry_price.toFixed(2) : '--'}</td>
          <td style="font-family:var(--mono)">${t.exit_price  != null ? '$'+t.exit_price.toFixed(2)  : '--'}</td>
          <td style="font-family:var(--mono)" class="${pnlCls}">${t.pnl != null ? (t.pnl>=0?'+':'')+t.pnl.toFixed(0) : '--'}</td>
          <td>${t.followed_plan ? '✓' : '✗'}</td>
          <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;font-size:10px">${esc(t.reason_entered || '')}</td>
        </tr>`;
      }).join('')}</tbody>
    </table></div>`;
  } catch (_) {}
}

/* ════════════════════════════════════════════════════════════════════════════
   Auction Intelligence Panel
   ════════════════════════════════════════════════════════════════════════════ */

function renderAuctionIntel(d) {
  const el = $('auctionIntelPanel');
  if (!el || !d) return;

  const ai = d.auction_intelligence;
  if (!ai || !ai.available) {
    el.innerHTML = '<div class="ai-waiting">Waiting for session volume profile...</div>';
    return;
  }

  const state   = ai.auction_state   || {};
  const poc_mig = ai.poc_migration   || {};
  const excess  = ai.excess          || {};
  const acc     = ai.acceptance      || {};
  const nodes   = ai.nodes           || {};
  const hvbo    = ai.hvbo            || {};

  // ── Auction State Block ──
  const stateName  = (state.state || '--').replace(/_/g, ' ');
  const dayType    = (state.day_type || '--').replace(/_/g, ' ');
  const partType   = state.participant_type || '';
  const isInit     = state.is_initiative;
  const isResp     = state.is_responsive;
  const isTrend    = state.is_trend_day;
  const isBalanced = state.is_balanced;
  const stateConf  = state.confidence || 0;
  const wouldTrade = state.would_trade;
  const stateColor = isTrend ? 'var(--green)' : isInit ? '#22d3ee' : isResp ? 'var(--amber)' : 'var(--muted)';

  // ── POC Migration Block ──
  const pocDir   = poc_mig.direction || 'UNKNOWN';
  const pocSpeed = poc_mig.speed || '';
  const pocAccel = poc_mig.acceleration || '';
  const pocColor = pocDir === 'RISING' ? 'var(--green)' : pocDir === 'FALLING' ? 'var(--red)' : 'var(--muted)';
  const pocArrow = pocDir === 'RISING' ? '▲' : pocDir === 'FALLING' ? '▼' : '—';

  // ── Excess ──
  const excessDetected = excess.detected;
  const excessType = (excess.type || '').replace(/_/g,' ');
  const excessConf = excess.confidence || 0;

  // ── Acceptance ──
  const accStatus = acc.primary_status || '';
  const accLevel  = acc.primary_level  || '';
  const accConf   = acc.primary_confidence || 0;
  const accColor  = accStatus === 'ACCEPTING' ? 'var(--green)' : accStatus === 'REJECTED' ? 'var(--red)' : 'var(--amber)';

  // ── HVBO ──
  const hvboLow  = hvbo.hvbo_low;
  const hvboHigh = hvbo.hvbo_high;
  const hvboMid  = hvbo.hvbo_mid;
  const hvboLoc  = (hvbo.price_location || '').replace(/_/g,' ');
  const vaStatus = (hvbo.va_status || '').replace(/_/g,' ');

  // ── Node intelligence ──
  const callNote  = nodes.call_target_note || '';
  const putNote   = nodes.put_target_note  || '';
  const fastZone  = nodes.fast_zone_warning || '';

  el.innerHTML = `
    <div class="ai-grid">

      <div class="ai-block">
        <div class="ai-block-label">Auction State</div>
        <div class="ai-state-name" style="color:${stateColor}">${esc(stateName)}</div>
        <div class="ai-state-meta">
          ${esc(dayType)} &middot; ${esc(partType.replace(/_/g,' '))} &middot; ${stateConf}% confidence
        </div>
        <div class="ai-participation ${wouldTrade ? 'ai-trade-yes' : 'ai-trade-no'}">
          ${wouldTrade ? '✓ Institutional traders would participate' : '✗ Wait for better structure'}
        </div>
        <div class="ai-narrative">${esc(state.explanation || '')}</div>
      </div>

      <div class="ai-block">
        <div class="ai-block-label">POC Migration</div>
        <div class="ai-poc-dir" style="color:${pocColor}">${pocArrow} ${esc(pocDir)} <span class="ai-poc-speed">${esc(pocSpeed)} ${pocAccel ? '· '+esc(pocAccel) : ''}</span></div>
        ${poc_mig.current_poc ? `<div class="ai-poc-levels">Current POC: <b>$${fmt(poc_mig.current_poc)}</b> · Prior: $${fmt(poc_mig.prior_poc)}</div>` : ''}
        <div class="ai-narrative">${esc(poc_mig.narrative || '')}</div>
      </div>

      <div class="ai-block">
        <div class="ai-block-label">Acceptance / Rejection</div>
        <div class="ai-acc-status" style="color:${accColor}">${esc(accStatus)} at ${esc(accLevel)} <span class="ai-acc-conf">${accConf}%</span></div>
        <div class="ai-narrative">${esc(acc.primary_note || '')}</div>
      </div>

      <div class="ai-block">
        <div class="ai-block-label">HVBO Zone</div>
        ${hvboLow && hvboHigh ? `<div class="ai-hvbo-range"><b>$${fmt(hvboLow)} – $${fmt(hvboHigh)}</b> <span class="ai-hvbo-mid">mid $${fmt(hvboMid)}</span></div>` : '<div class="ai-waiting">Building...</div>'}
        <div class="ai-hvbo-loc">${esc(hvboLoc)}</div>
        <div class="ai-narrative">${esc(hvbo.va_note || '')}</div>
      </div>

    </div>

    ${excessDetected ? `
    <div class="ai-excess-alert ${excess.type?.includes('BEARISH') ? 'ai-excess-bear' : 'ai-excess-bull'}">
      <div class="ai-excess-label">⚠ ${esc(excessType)} — ${excessConf}% confidence</div>
      <div class="ai-excess-text">${esc(excess.narrative || '')}</div>
      ${excess.action ? `<div class="ai-excess-action">${esc(excess.action)}</div>` : ''}
    </div>` : ''}

    ${callNote || putNote ? `
    <div class="ai-targets">
      ${callNote ? `<div class="ai-target-call">▲ ${esc(callNote)}</div>` : ''}
      ${putNote  ? `<div class="ai-target-put">▼ ${esc(putNote)}</div>`  : ''}
    </div>` : ''}

    ${fastZone ? `<div class="ai-fast-zone">⚡ ${esc(fastZone)}</div>` : ''}
  `;
}

/* ════════════════════════════════════════════════════════════════════════════
   DECISION TREE — 6-layer institutional hierarchy
   ════════════════════════════════════════════════════════════════════════════ */

function renderDecisionTree(d) {
  const el = $('decisionTreePanel');
  if (!el || !d) return;

  const ms    = d.market_state || {};
  const ai    = d.auction_intelligence || {};
  const ici   = d.ici || {};
  const exec  = d.execution || {};
  const flow  = d.flow_intelligence || d.flow || {};
  const gamma = d.gamma_regime || {};
  const risk  = d.risk || {};
  const state = d.decision_state || 'NO_TRADE';

  // Layer 1: Environment
  const session   = (d.session || {}).session_state || ms.session_state || '';
  const tradeable = session === 'MARKET_OPEN';
  const env_ok    = tradeable;
  const env_label = tradeable ? 'Tradeable' : session.replace(/_/g,' ');

  // Layer 2: Auction
  const aiState   = ai.auction_state || {};
  const auctionOk = aiState.would_trade === true;
  const auction_label = (aiState.state || (d.auction||{}).auction_state || 'UNKNOWN').replace(/_/g,' ');
  const mig = ms.poc_migration || '';
  const pva = ms.price_vs_va  || '';

  // Layer 3: Institutional participation
  const flowBias  = ms.flow_bias || flow.bias || 'MIXED';
  const tapeBias  = ms.tape_bias || 'MIXED';
  const sweeps    = ms.tape_sweeps || 0;
  const netPrem   = ms.net_premium || 0;
  const flowOk    = flowBias === 'BULLISH' && state.includes('CALL') ||
                    flowBias === 'BEARISH' && state.includes('PUT') ||
                    flowBias !== 'MIXED';
  const flow_label = `Flow ${esc(flowBias)} · Tape ${esc(tapeBias)}${sweeps > 0 ? ' · '+sweeps+' sweeps' : ''}`;

  // Layer 4: Structure
  const pocOk  = ms.poc > 0;
  const conf   = ms.poc_vwap_confluent;
  const accStatus = (ai.acceptance || {}).primary_status || '';
  const struct_label = accStatus ? `${esc(accStatus)} at ${esc((ai.acceptance||{}).primary_level||'')}` : (pocOk ? 'Levels defined' : 'Waiting for profile');
  const structOk = accStatus === 'ACCEPTING' || accStatus === 'TESTING';

  // Layer 5: Execution (Pine)
  const pine   = ms.pine_state || 'WAITING';
  const pineOk = pine === 'CONFIRMED';
  const pine_secs = ms.signal_secs || 0;
  const pine_label = pineOk ? `Pine Confirmed${pine_secs > 0 ? ' ('+Math.floor(pine_secs/60)+'m '+pine_secs%60+'s)' : ''}` : 'Waiting for Pine';

  // Layer 6: Decision
  const isEnter   = state.startsWith('ENTER');
  const isWatch   = state.startsWith('WATCH') || state === 'READY';
  const dec_color = isEnter ? 'var(--green)' : isWatch ? 'var(--amber)' : 'var(--red)';

  const _layer = (num, label, value, ok, note='') => {
    const dot = ok === true ? 'dt-dot-green' : ok === false ? 'dt-dot-red' : 'dt-dot-amber';
    return `<div class="dt-layer">
      <div class="dt-layer-left">
        <div class="dt-dot ${dot}"></div>
        <div class="dt-connector"></div>
      </div>
      <div class="dt-layer-body">
        <div class="dt-layer-label">${label}</div>
        <div class="dt-layer-value">${value}</div>
        ${note ? `<div class="dt-layer-note">${esc(note)}</div>` : ''}
      </div>
    </div>`;
  };

  el.innerHTML = `
    <div class="dt-wrap">
      ${_layer(1, 'Environment',              env_label,     env_ok,    tradeable ? '' : 'Market closed — no entries')}
      ${_layer(2, 'Auction',                  auction_label, auctionOk, aiState.explanation ? aiState.explanation.slice(0,120)+'…' : '')}
      ${_layer(3, 'Institutional Flow',       flow_label,    flowOk,    '')}
      ${_layer(4, 'Structure / Acceptance',   struct_label,  structOk,  (ai.acceptance||{}).primary_note ? (ai.acceptance.primary_note).slice(0,100)+'…' : '')}
      ${_layer(5, 'Execution',                pine_label,    pineOk,    '')}
      <div class="dt-decision" style="color:${dec_color}">
        <div class="dt-decision-label">Decision</div>
        <div class="dt-decision-state">${esc(state.replace(/_/g,' '))}</div>
        <div class="dt-decision-ici">ICI ${fmtI(Number(ici.ici||0))}</div>
      </div>
    </div>
  `;
}

/* ════════════════════════════════════════════════════════════════════════════
   INSTITUTIONAL TIMELINE — chronological event feed
   ════════════════════════════════════════════════════════════════════════════ */

// Deduplicated event log — only logs meaningful state changes
const timelineEvents = [];
let lastTimelineState = '';

function captureTimelineEvent(d) {
  if (!d) return;
  const ms     = d.market_state || {};
  const ai     = d.auction_intelligence || {};
  const state  = d.decision_state || '';
  const mig    = ms.poc_migration || '';
  const accS   = (ai.acceptance || {}).primary_status || '';
  const accL   = (ai.acceptance || {}).primary_level  || '';
  const excess = (ai.excess || {}).detected ? (ai.excess.type||'') : '';
  const pine   = ms.pine_state || '';
  const flow   = ms.flow_bias  || '';
  const tape   = ms.tape_bias  || '';
  const auctionState = ((ai.auction_state||{}).state||'').replace(/_/g,' ');

  // Build a fingerprint of the meaningful state
  const fp = [state, mig, accS, accL, excess, pine, flow, auctionState].join('|');
  if (fp === lastTimelineState) return;  // no change — skip
  lastTimelineState = fp;

  const ts  = new Date().toLocaleTimeString('en-US', {
    hour: '2-digit', minute: '2-digit', hour12: true, timeZone: 'America/New_York'
  });

  // Determine the most meaningful event to log
  const events = [];

  if (excess) {
    events.push({ text: excess.replace(/_/g,' '), type: excess.includes('BEARISH') ? 'bear' : 'bull', icon: '⚠' });
  }
  if (pine === 'CONFIRMED' && !lastTimelineState.includes('CONFIRMED')) {
    events.push({ text: 'Pine trigger confirmed', type: 'signal', icon: '🎯' });
  }
  if (mig === 'RISING') {
    events.push({ text: 'POC migrating higher — institutions accepting higher prices', type: 'bull', icon: '▲' });
  } else if (mig === 'FALLING') {
    events.push({ text: 'POC migrating lower — institutions distributing', type: 'bear', icon: '▼' });
  }
  if (accS === 'ACCEPTING') {
    events.push({ text: `Acceptance ${accS.toLowerCase()} at ${accL}`, type: 'bull', icon: '✓' });
  } else if (accS === 'REJECTED') {
    events.push({ text: `Rejection at ${accL}`, type: 'bear', icon: '✗' });
  }
  if (auctionState && auctionState !== 'UNKNOWN') {
    events.push({ text: auctionState, type: 'auction', icon: '⚡' });
  }
  if (flow === 'BULLISH') {
    events.push({ text: 'Flow turned bullish', type: 'bull', icon: '●' });
  } else if (flow === 'BEARISH') {
    events.push({ text: 'Flow turned bearish', type: 'bear', icon: '●' });
  }
  if (state.startsWith('ENTER')) {
    events.push({ text: state.replace(/_/g,' '), type: 'signal', icon: '▶' });
  }

  if (!events.length) {
    events.push({ text: state.replace(/_/g,' '), type: 'neutral', icon: '·' });
  }

  // Add all events at this timestamp
  for (const ev of events) {
    timelineEvents.unshift({ ts, ...ev });
  }
  while (timelineEvents.length > 80) timelineEvents.pop();

  renderInstitutionalTimeline();
}

function renderInstitutionalTimeline() {
  const el = $('institutionalTimeline');
  if (!el) return;
  if (!timelineEvents.length) {
    el.innerHTML = '<div class="itl-empty">Session events will appear here as the auction develops.</div>';
    return;
  }
  const typeColor = {
    bull:    'var(--green)',
    bear:    'var(--red)',
    signal:  '#22d3ee',
    auction: 'var(--purple)',
    neutral: 'var(--faint)',
  };
  el.innerHTML = timelineEvents.slice(0,30).map((ev, i) => `
    <div class="itl-event">
      <div class="itl-time">${ev.ts}</div>
      <div class="itl-connector">
        <div class="itl-dot" style="background:${typeColor[ev.type]||'var(--faint)'}"></div>
        ${i < timelineEvents.length - 1 ? '<div class="itl-line"></div>' : ''}
      </div>
      <div class="itl-text" style="color:${typeColor[ev.type]||'var(--muted)'}">${ev.icon} ${esc(ev.text)}</div>
    </div>`).join('');
}

/* Upgrade renderReplayList to show auction context */
function renderReplayList() {
  const el = $('replayEvents');
  if (!el) return;
  if (!replaySnaps.length) {
    el.innerHTML = '<div style="color:var(--faint);font-size:12px;padding:12px">No replay data yet.</div>';
    return;
  }
  el.innerHTML = [...replaySnaps].reverse().slice(0, 30).map(s => {
    const decColor = s.state.includes('CALL') ? 'var(--green)' : s.state.includes('PUT') ? 'var(--red)' : s.state.includes('WATCH') || s.state === 'READY' ? 'var(--amber)' : 'var(--muted)';
    const migArrow = s.poc_migration === 'RISING' ? '▲' : s.poc_migration === 'FALLING' ? '▼' : '—';
    const accColor = s.acceptance === 'ACCEPTING' ? 'var(--green)' : s.acceptance === 'REJECTED' ? 'var(--red)' : 'var(--muted)';
    return `<div class="replay-event">
      <span class="re-time">${s.ts}</span>
      <div class="re-dot" style="background:${decColor}"></div>
      <div class="re-text">
        <b style="color:${decColor}">${s.state.replace(/_/g,' ')}</b>
        ${s.poc > 0 ? ` · POC <span style="color:var(--purple)">$${fmt(s.poc)}</span> ${migArrow}` : ''}
        ${s.auction_state ? ` · <span style="color:var(--faint)">${esc(s.auction_state)}</span>` : ''}
        ${s.acceptance ? ` · <span style="color:${accColor}">${esc(s.acceptance)}${s.acc_level?' @ '+esc(s.acc_level):''}</span>` : ''}
        ${s.excess ? `<br><span style="color:var(--amber)">⚠ ${esc(s.excess)}</span>` : ''}
        ${s.pine_state === 'CONFIRMED' ? `<br><span style="color:#22d3ee">🎯 Pine confirmed</span>` : ''}
      </div>
    </div>`;
  }).join('');
}

/* ════════════════════════════════════════════════════════════════════════════
   AUCTION LADDER — 2-second institutional read
   ════════════════════════════════════════════════════════════════════════════ */

function renderAuctionLadder(d) {
  const el = $('auctionLadder');
  if (!el || !d) return;

  const ms  = d.market_state || {};
  const ai  = d.auction_intelligence || {};
  const au  = d.auction  || {};
  const vp  = d.volume_profile || {};
  const lvl = vp.levels || {};

  const price  = ms.price   || 0;
  const poc    = ms.poc     || lvl.poc || au.poc || 0;
  const vah    = ms.vah     || lvl.vah || au.vah || 0;
  const val_   = ms.val     || lvl.val || au.val || 0;
  const vwap   = ms.vwap    || 0;
  const mig    = ms.poc_migration || au.poc_migration || '--';
  const pvp    = ms.price_vs_poc  || '';
  const pva    = ms.price_vs_va   || '';

  const aiState  = ai.auction_state  || {};
  const aiAcc    = ai.acceptance     || {};
  const aiPocMig = ai.poc_migration  || {};
  const aiExcess = ai.excess         || {};

  const pocDelta   = aiPocMig.delta || 0;
  const pocAccel   = aiPocMig.acceleration || '';
  const auctionConf= aiState.confidence || au.confidence || 0;
  const accStatus  = aiAcc.primary_status || '';
  const accLevel   = aiAcc.primary_level  || '';
  const wouldTrade = aiState.would_trade;
  const isInit     = aiState.is_initiative;
  const isResp     = aiState.is_responsive;
  const isTrend    = aiState.is_trend_day;
  const auctionStateName = (aiState.state || au.auction_state || '').replace(/_/g, ' ');

  // ── Price location label ──
  const priceLoc =
    pva === 'ABOVE_VAH' ? '▲ ABOVE VALUE' :
    pva === 'BELOW_VAL' ? '▼ BELOW VALUE' :
    pvp === 'ABOVE'     ? '▲ ABOVE POC'   :
    pvp === 'BELOW'     ? '▼ BELOW POC'   :
    pvp === 'AT'        ? '— AT POC'       : '— INSIDE VALUE';

  const priceLocColor =
    pva === 'ABOVE_VAH'             ? 'var(--green)'  :
    pva === 'BELOW_VAL'             ? 'var(--red)'    :
    pvp === 'ABOVE'                 ? 'var(--green)'  :
    pvp === 'BELOW'                 ? 'var(--red)'    : 'var(--muted)';

  // ── POC migration label ──
  const pocMigLabel =
    mig === 'RISING'  ? '▲ Rising' :
    mig === 'FALLING' ? '▼ Falling' : '— Stable';
  const pocMigSub = pocDelta !== 0
    ? (pocDelta > 0 ? '+' : '') + pocDelta.toFixed(2) + ' pts' +
      (pocAccel === 'ACCELERATING' ? ' · ↑↑ accel' : pocAccel === 'DECELERATING' ? ' · slowing' : '')
    : '';
  const migColor = mig === 'RISING' ? 'var(--green)' : mig === 'FALLING' ? 'var(--red)' : 'var(--muted)';

  // ── Auction state label ──
  const auctionLabel =
    pva === 'ABOVE_VAH' && mig === 'RISING'  ? 'Accepting Higher'       :
    pva === 'ABOVE_VAH' && mig === 'STABLE'  ? 'Testing Higher — Probe' :
    pva === 'ABOVE_VAH' && mig === 'FALLING' ? 'Rejection Risk'         :
    pva === 'BELOW_VAL' && mig === 'FALLING' ? 'Accepting Lower'        :
    pva === 'BELOW_VAL' && mig === 'STABLE'  ? 'Lower Probe — Not Accepted' :
    pva === 'BELOW_VAL' && mig === 'RISING'  ? 'Failed Breakdown'       :
    accStatus === 'REJECTED'                  ? 'Rejected at Level'      :
    isTrend                                   ? auctionStateName          :
    isInit                                    ? auctionStateName          :
    isResp                                    ? auctionStateName          :
    mig === 'RISING'                          ? 'Building Higher — Inside Value' :
    mig === 'FALLING'                         ? 'Building Lower — Inside Value'  :
    auctionStateName || 'Balanced';

  const auctionColor =
    auctionLabel.includes('Accepting Higher') || auctionLabel.includes('Failed Breakdown') ? 'var(--green)' :
    auctionLabel.includes('Accepting Lower')  || auctionLabel.includes('Rejection') ? 'var(--red)' :
    auctionLabel.includes('Probe') || auctionLabel.includes('Testing') ? 'var(--amber)' :
    isTrend || isInit ? '#22d3ee' : 'var(--muted)';

  // ── Acceptance ──
  const accLabel = accStatus
    ? accStatus + (accLevel ? ' at ' + accLevel : '')
    : '—';
  const accColor = accStatus === 'ACCEPTING' ? 'var(--green)' : accStatus === 'REJECTED' ? 'var(--red)' : 'var(--amber)';
  const accYN    = accStatus === 'ACCEPTING' ? '✓ YES' : accStatus === 'REJECTED' ? '✗ NO' : '~ TESTING';

  // ── Institutional bias (the split-brain read) ──
  const biasBull =
    pva === 'ABOVE_VAH' && mig === 'RISING'  ? 'Bullish price & auction'   :
    pva === 'ABOVE_VAH' && mig === 'STABLE'  ? 'Bullish price'             :
    pva === 'ABOVE_VAH' && mig === 'FALLING' ? 'Bullish price'             :
    pva === 'BELOW_VAL' && mig === 'RISING'  ? 'Bullish auction'           :
    mig === 'RISING'                          ? 'Bullish value'             : null;

  const biasBear =
    pva === 'BELOW_VAL' && mig === 'FALLING' ? 'Bearish price & auction'   :
    pva === 'BELOW_VAL' && mig === 'STABLE'  ? 'Bearish price'             :
    pva === 'ABOVE_VAH' && mig === 'FALLING' ? 'Bearish auction'           :
    pva === 'BELOW_VAL' && mig === 'RISING'  ? 'Bearish price'             :
    mig === 'FALLING'                         ? 'Bearish value'             : null;

  const biasConflict = biasBull && biasBear;

  // ── Excess ──
  const excessType = aiExcess.detected ? (aiExcess.type || '').replace(/_/g, ' ') : null;

  // ── Participation ──
  const participationLabel = wouldTrade === false
    ? 'Wait — no institutional setup'
    : isInit   ? 'Initiative participants active'
    : isResp   ? 'Responsive participants active'
    : isTrend  ? 'Trend day — momentum favored'
    : 'Balanced — no clear participants';
  const participationColor = wouldTrade === false ? 'var(--faint)'
    : (isInit || isTrend) ? '#22d3ee' : isResp ? 'var(--amber)' : 'var(--faint)';

  // ── Build the ladder ──
  const _row = (label, value, sub, valueColor) => `
    <div class="al-row">
      <div class="al-label">${esc(label)}</div>
      <div class="al-value" style="color:${valueColor||'var(--text)'}">${value}</div>
      ${sub ? `<div class="al-sub">${esc(sub)}</div>` : ''}
    </div>`;

  const _div = () => `<div class="al-divider"></div>`;

  el.innerHTML = `
    <div class="al-wrap">

      ${excessType ? `<div class="al-excess-banner">${excessType}</div>` : ''}

      ${_row('Price', price > 0 ? '$' + fmt(price) : '—', priceLoc, priceLocColor)}
      ${_row('POC',   poc   > 0 ? '$' + fmt(poc)   : '—', pocMigLabel + (pocMigSub ? ' · ' + pocMigSub : ''), 'var(--purple)')}
      ${_row('VAH',   vah   > 0 ? '$' + fmt(vah)   : '—', '', 'var(--amber)')}
      ${_row('VAL',   val_  > 0 ? '$' + fmt(val_)  : '—', '', 'var(--amber)')}
      ${vwap > 0 ? _row('VWAP', '$' + fmt(vwap), '', 'var(--blue)') : ''}

      ${_div()}

      ${_row('POC Migration', pocMigLabel, pocMigSub, migColor)}

      ${_div()}

      <div class="al-row al-row-feature">
        <div class="al-label">Auction</div>
        <div class="al-value al-value-feature" style="color:${auctionColor}">${esc(auctionLabel)}</div>
        ${auctionConf > 0 ? `<div class="al-sub">${auctionConf}% confidence</div>` : ''}
      </div>

      ${_div()}

      <div class="al-row">
        <div class="al-label">Acceptance</div>
        <div class="al-value" style="color:${accColor}">${accYN}</div>
        <div class="al-sub">${esc(accLabel)}</div>
      </div>

      ${_div()}

      <div class="al-row al-row-bias">
        <div class="al-label">Institutional Bias</div>
        <div class="al-bias-values">
          ${biasBull ? `<span class="al-bias-bull">▲ ${esc(biasBull)}</span>` : ''}
          ${biasBear ? `<span class="al-bias-bear">▼ ${esc(biasBear)}</span>` : ''}
          ${!biasBull && !biasBear ? '<span style="color:var(--faint)">Neutral</span>' : ''}
        </div>
        ${biasConflict ? '<div class="al-bias-conflict">⚡ Bias conflict — divergence condition</div>' : ''}
      </div>

      ${_div()}

      <div class="al-participation" style="color:${participationColor}">
        ${esc(participationLabel)}
      </div>

    </div>
  `;
}

/* ── Inner tabs (within cards) ────────────────────────────────────────────── */
function initInnerTabs() {
  document.querySelectorAll('.db-inner-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      const key = btn.dataset.inner;
      // Find parent tab container
      const parent = btn.closest('.card, .db-command-card, .db-analytics-card');
      if (!parent) return;
      // Deactivate all sibling tabs and panes
      parent.querySelectorAll('.db-inner-tab').forEach(b => b.classList.remove('active'));
      parent.querySelectorAll('.db-inner-pane').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      const pane = document.getElementById('db-inner-' + key);
      if (pane) pane.classList.add('active');
    });
  });
}

/* ════════════════════════════════════════════════════════════════════════════
   OPERATOR FLOW PANEL — compact inline flow summary for Band 3
   ════════════════════════════════════════════════════════════════════════════ */

function renderOpFlow(d) {
  const el = $('opFlowPanel');
  if (!el || !d) return;
  const fi  = d.flow_intelligence || d.flow || {};
  const ms  = d.market_state || {};
  const tape = d.flow_tape_summary || {};

  const flowBias   = ms.flow_bias   || fi.bias   || 'MIXED';
  const tapeBias   = ms.tape_bias   || 'MIXED';
  const netPrem    = ms.net_premium || fi.net_premium || 0;
  const callPrem   = ms.call_premium|| fi.call_premium || 0;
  const putPrem    = ms.put_premium || fi.put_premium  || 0;
  const sweeps     = ms.tape_sweeps || tape.sweep_count || fi.sweep_count || 0;
  const blocks     = ms.tape_blocks || tape.block_count || 0;
  const blockConv  = fi.block_conviction || '';
  const divType    = ms.divergence_type || fi.divergence_type || '';

  const biasColor = flowBias === 'BULLISH' ? 'var(--green)' : flowBias === 'BEARISH' ? 'var(--red)' : 'var(--muted)';
  const tapeColor = tapeBias === 'BULLISH' ? 'var(--green)' : tapeBias === 'BEARISH' ? 'var(--red)' : 'var(--muted)';

  // Block conviction interpretation
  const convInterpret = (() => {
    if (blockConv === 'HIGH' && flowBias === 'MIXED')
      return { label: 'HIGH ACTIVITY · NO DIRECTION', note: 'Institutions active but fighting each other. Expect rotational trade.', color: 'var(--amber)' };
    if (blockConv === 'HIGH' && flowBias === 'BULLISH')
      return { label: 'HIGH ACTIVITY · BULLISH', note: 'Large institutions buying. Directional conviction confirmed.', color: 'var(--green)' };
    if (blockConv === 'HIGH' && flowBias === 'BEARISH')
      return { label: 'HIGH ACTIVITY · BEARISH', note: 'Large institutions selling. Directional conviction confirmed.', color: 'var(--red)' };
    if (blockConv === 'LOW')
      return { label: 'LOW ACTIVITY', note: 'Institutional participation is light.', color: 'var(--faint)' };
    return null;
  })();

  el.innerHTML = `
    <div class="op-flow-grid">
      <div class="op-flow-item">
        <div class="op-flow-label">Flow Bias</div>
        <div class="op-flow-val" style="color:${biasColor}">${esc(flowBias)}</div>
      </div>
      <div class="op-flow-item">
        <div class="op-flow-label">Tape Bias</div>
        <div class="op-flow-val" style="color:${tapeColor}">${esc(tapeBias)}</div>
      </div>
      <div class="op-flow-item">
        <div class="op-flow-label">Net Premium</div>
        <div class="op-flow-val" style="color:${netPrem>=0?'var(--green)':'var(--red)'}">${netPrem>=0?'+':''}${fmtM(netPrem)}</div>
      </div>
      <div class="op-flow-item">
        <div class="op-flow-label">Sweeps / Blocks</div>
        <div class="op-flow-val">${sweeps} / ${blocks}</div>
      </div>
    </div>

    ${convInterpret ? `
    <div class="op-conv-block" style="border-color:${convInterpret.color}20;background:${convInterpret.color}08">
      <div class="op-conv-label" style="color:${convInterpret.color}">${esc(convInterpret.label)}</div>
      <div class="op-conv-note">${esc(convInterpret.note)}</div>
    </div>` : ''}

    ${divType ? `<div class="op-div-alert">⚡ ${esc(divType.replace(/_/g,' '))} divergence active</div>` : ''}

    <div class="op-flow-prems">
      <div class="op-prem-row">
        <span class="op-prem-label">Call premium</span>
        <span class="op-prem-val rv-green">$${fmtM(callPrem)}</span>
      </div>
      <div class="op-prem-row">
        <span class="op-prem-label">Put premium</span>
        <span class="op-prem-val rv-red">$${fmtM(putPrem)}</span>
      </div>
    </div>
  `;
}

/* ════════════════════════════════════════════════════════════════════════════
   EXECUTIVE SUMMARY — hero panel at top of dashboard
   ════════════════════════════════════════════════════════════════════════════ */

function renderExecutiveSummary(d) {
  const el = $('execSummaryHero');
  if (!el || !d) return;

  const story   = d.story || {};
  const ms      = d.market_state || {};
  const session = (d.session || {}).session_state || ms.session_state || '';
  const fi      = d.flow_intelligence || d.flow || {};
  const on_plan = d.overnight_game_plan;
  const summary = d.executive_summary || story.executive_summary || '';
  const state   = d.decision_state || 'NO_TRADE';

  const isOvernight  = session === 'OVERNIGHT' || session === 'PREMARKET';
  const isClosed     = session === 'CLOSED';
  const isNoTrade    = state === 'NO_TRADE' || state === 'PREPARING';
  const isActionable = state.startsWith('ENTER') || state.startsWith('WATCH') || state === 'READY';

  const stateColor = state.startsWith('ENTER') ? 'var(--green)' :
                     (state.startsWith('WATCH') || state === 'READY') ? 'var(--amber)' : 'var(--muted)';

  // Block conviction vs bias surfaced here
  const blockConv = fi.block_conviction || '';
  const flowBias  = ms.flow_bias || fi.bias || 'MIXED';
  const netPrem   = ms.net_premium || fi.net_premium || 0;
  const blockHtml = blockConv && blockConv !== 'NONE' && blockConv !== 'LOW' ? `
    <div class="exec-block-row">
      <div class="exec-block-item">
        <div class="exec-block-label">Institutional Activity</div>
        <div class="exec-block-val" style="color:${blockConv==='HIGH'?'var(--amber)':'var(--muted)'}">${esc(blockConv)}</div>
      </div>
      <div class="exec-block-item">
        <div class="exec-block-label">Direction</div>
        <div class="exec-block-val" style="color:${flowBias==='BULLISH'?'var(--green)':flowBias==='BEARISH'?'var(--red)':'var(--muted)'}">${esc(flowBias)}</div>
      </div>
      ${blockConv === 'HIGH' && flowBias === 'MIXED' ? `<div class="exec-block-note">Large institutions active but not aligned — expect two-way trade until one side takes control.</div>` : ''}
    </div>` : '';

  // Overnight plan gets priority when markets closed
  if (isOvernight && on_plan && on_plan.game_plan) {
    const bias = on_plan.bias || 'NEUTRAL';
    const biasColor = bias.includes('BULL') ? 'var(--green)' : bias.includes('BEAR') ? 'var(--red)' : 'var(--amber)';
    const biasArrow = bias.includes('BULL') ? '▲' : bias.includes('BEAR') ? '▼' : '—';
    el.innerHTML = `
      <div class="exec-session-badge exec-overnight">☾ OVERNIGHT GAME PLAN</div>
      <div class="exec-bias-row">
        <span class="exec-bias" style="color:${biasColor}">${biasArrow} ${esc(bias.replace(/_/g,' '))}</span>
        ${on_plan.next_rth ? `<span class="exec-next-rth">Cash open: ${esc(on_plan.next_rth)}</span>` : ''}
      </div>
      <div class="exec-narrative">${esc(on_plan.executive_summary || summary)}</div>
      ${on_plan.game_plan ? `<div class="exec-game-plan">${esc(on_plan.game_plan)}</div>` : ''}
      ${blockHtml}`;
    return;
  }

  if (isClosed) {
    el.innerHTML = `
      <div class="exec-session-badge exec-closed">● CLOSED SESSION</div>
      <div class="exec-narrative">${esc(summary || "Market closed. Review the day's auction and prepare for tomorrow.")}</div>
      ${blockHtml}`;
    return;
  }

  // Regular session — show the executive summary prominently
  el.innerHTML = `
    <div class="exec-state-row">
      <span class="exec-state-badge" style="color:${stateColor};border-color:${stateColor}">${esc(state.replace(/_/g,' '))}</span>
      ${story.engine ? `<span class="exec-engine-tag">${esc(story.engine)}</span>` : ''}
    </div>
    <div class="exec-narrative ${isActionable ? 'exec-narrative-active' : ''}">${esc(summary)}</div>
    ${blockHtml}`;
}

/* ════════════════════════════════════════════════════════════════════════════
   DEALER POSITIONING PANEL
   ════════════════════════════════════════════════════════════════════════════ */

function renderDealerPanel(d) {
  const el = $('dealerPanel');
  if (!el || !d) return;
  const dp = d.dealer_positioning;
  if (!dp || !dp.available) {
    el.innerHTML = '<div class="sk-waiting">⌛ Building dealer model...</div>';
    return;
  }

  const g   = dp.gamma   || {};
  const dt_ = dp.delta   || {};
  const ch  = dp.charm   || {};
  const ve  = dp.vega    || {};
  const hp  = dp.hedging_pressure || {};
  const pin = dp.pin_probability  || {};
  const mom = dp.momentum_probability || {};

  const regimeColor = g.regime === 'POSITIVE_GAMMA' ? 'var(--green)' : g.regime === 'NEGATIVE_GAMMA' ? 'var(--red)' : 'var(--muted)';
  const deltaColor  = dt_.bias === 'BUYING' ? 'var(--green)' : dt_.bias === 'SELLING' ? 'var(--red)' : 'var(--muted)';
  const charmColor  = ch.charm === 'POSITIVE' ? 'var(--green)' : ch.charm === 'NEGATIVE' ? 'var(--red)' : 'var(--muted)';
  const momColor    = mom.probability >= 70 ? 'var(--green)' : mom.probability >= 45 ? 'var(--amber)' : 'var(--red)';

  const _row = (label, val, color, sub='') => `
    <div class="dp-row">
      <div class="dp-label">${label}</div>
      <div class="dp-val" style="color:${color}">${esc(val)}</div>
      ${sub ? `<div class="dp-sub">${esc(sub)}</div>` : ''}
    </div>`;

  el.innerHTML = `
    ${_row('Gamma',    (g.regime||'--').replace(/_/g,' '),    regimeColor, g.expected_volatility ? 'Vol: '+g.expected_volatility : '')}
    ${_row('Delta',    dt_.bias||'--',                        deltaColor,  dt_.confidence ? `${dt_.confidence.toFixed(0)}% confidence` : '')}
    ${_row('Charm',    ch.charm||'--',                        charmColor,  ch.charm_bias ? ch.charm_bias.replace(/_/g,' ') : '')}
    ${_row('Vega',     ve.vega||'--',                         'var(--muted)', ve.vix_environment ? ve.vix_environment.replace(/_/g,' ') : '')}
    ${_row('Hedging',  hp.level||'--',                        hp.level==='HIGH'?'var(--amber)':'var(--muted)', hp.direction||'')}
    ${_row('Pin Prob', `${fmtI(pin.probability||0)}%`,        pin.level==='HIGH'?'var(--amber)':'var(--muted)', pin.pin_note||'')}
    ${_row('Momentum', `${fmtI(mom.probability||0)}%`,        momColor,    mom.level||'')}
    <div class="dp-summary">${esc(dp.dealer_summary||'')}</div>
  `;
}

/* ════════════════════════════════════════════════════════════════════════════
   INSTITUTIONAL PLAYBOOK PANEL
   ════════════════════════════════════════════════════════════════════════════ */

function renderPlaybook(d) {
  const el = $('playbookPanel');
  if (!el || !d) return;
  const pb = d.playbook;
  if (!pb || !pb.available) {
    el.innerHTML = '<div class="sk-waiting">⌛ Building playbook...</div>';
    return;
  }

  const st  = pb.session_type || {};
  const pri = pb.primary_scenario || {};
  const alt = pb.alternate_scenario || {};
  const priColor = pri.direction === 'BULLISH' ? 'var(--green)' : pri.direction === 'BEARISH' ? 'var(--red)' : 'var(--muted)';
  const altColor = alt.direction === 'BULLISH' ? 'var(--green)' : alt.direction === 'BEARISH' ? 'var(--red)' : 'var(--muted)';

  el.innerHTML = `
    <div class="pb-session-type">${esc(st.type||'').replace(/_/g,' ')}</div>
    <div class="pb-dealer">${esc(pb.dealer_header||'')}</div>

    <div class="pb-scenario pb-primary">
      <div class="pb-scenario-label" style="color:${priColor}">Primary — ${esc(pri.direction||'')} · ${fmtI(pri.probability||0)}%</div>
      <div class="pb-scenario-title">${esc(pri.title||'')}</div>
      <div class="pb-scenario-path">${esc(pri.path||'')}</div>
      <div class="pb-scenario-entry">Entry: ${esc(pri.entry||'--')}</div>
      <div class="pb-scenario-meta">
        <span>T: ${esc(pri.target||'--')}</span>
        <span>Stop: ${esc(pri.stop||'--')}</span>
      </div>
    </div>

    <div class="pb-scenario pb-alternate">
      <div class="pb-scenario-label" style="color:${altColor}">Alternate — ${esc(alt.direction||'')} · ${fmtI(alt.probability||0)}%</div>
      <div class="pb-scenario-title">${esc(alt.title||'')}</div>
      <div class="pb-scenario-path">${esc(alt.path||'')}</div>
      <div class="pb-trigger">Trigger: ${esc(alt.trigger||'--')}</div>
    </div>

    <div class="pb-invalidation">
      <div class="pb-inv-label">Invalidation</div>
      <div class="pb-inv-text">${esc(pb.invalidation||'')}</div>
    </div>

    <div class="pb-next">${esc(pb.next_event||'')}</div>
  `;
}

/* ════════════════════════════════════════════════════════════════════════════
   INSTITUTIONAL INTELLIGENCE — Four Pillar dashboard panel
   ════════════════════════════════════════════════════════════════════════════ */

function renderInstitutionalIntelligence(d) {
  const el = $('instIntelPanel');
  if (!el || !d) return;

  const ii = d.institutional_intelligence;
  if (!ii || !ii.available) {
    el.innerHTML = '<div class="sk-waiting">⌛ Building institutional intelligence...<br><span style="font-size:10px;color:var(--faint)">Populates after the first completed scan cycle.</span></div>';
    return;
  }

  const scoreColor = s => Number(s) >= 70 ? 'var(--green)' : Number(s) >= 50 ? 'var(--amber)' : 'var(--red)';
  const alignment  = (ii.alignment || '').toString();
  const alignColor = alignment.includes('FULL') && alignment.includes('BULL') ? 'var(--green)' :
                     alignment.includes('FULL') && alignment.includes('BEAR') ? 'var(--red)'   :
                     alignment.includes('PARTIAL') ? 'var(--amber)' : 'var(--faint)';

  // Support both v6.5 pillars and v7.0 flat structure
  const pillars = ii.pillars || {};
  const p1 = pillars.market_structure || {};
  const p2 = pillars.dealer           || {};
  const p3 = pillars.institutional    || {};
  const p4 = pillars.execution        || {};

  const dp = d.dealer_positioning || {};
  const md = d.market_drivers     || {};

  const msScore  = p1.score  || ii.market_structure_score  || 50;
  const dScore   = p2.score  || ii.dealer_score             || 50;
  const instScore= p3.score  || ii.institutional_score      || 50;
  const execScore= p4.score  || ii.execution_score          || 50;
  const msDir    = p1.direction || (ii.auction_bias||'').includes('HIGHER') ? 'BULLISH' : (ii.auction_bias||'').includes('LOWER') ? 'BEARISH' : 'NEUTRAL';
  const dDir     = p2.direction || (ii.delta_bias === 'BUYING' ? 'BULLISH' : ii.delta_bias === 'SELLING' ? 'BEARISH' : 'NEUTRAL');
  const instDir  = p3.direction || (ii.flow_bias === 'BULLISH' ? 'BULLISH' : ii.flow_bias === 'BEARISH' ? 'BEARISH' : 'NEUTRAL');
  const execDir  = p4.decision_state || ii.decision_state || 'NO_TRADE';
  const msNote   = p1.narrative || (ii.auction_state||'--') + ' · POC ' + (ii.poc_migration||'STABLE').toLowerCase();
  const dNote    = p2.narrative || 'Gamma: ' + (ii.gamma_regime||'--').replace(/_/g,' ') + ' · Delta: ' + (ii.delta_bias||'--') + ' · Pin ' + (ii.pin_probability||0).toFixed(0) + '%';
  const instNote = p3.narrative || 'Flow ' + (ii.flow_bias||'--') + ' · Conviction ' + (ii.flow_conviction||0).toFixed(0) + ' · ' + (ii.flow_urgency||'LOW') + ' urgency';
  const execNote = p4.narrative || (ii.decision_state||'NO_TRADE').replace(/_/g,' ') + ' · ICI ' + (ii.ici_score||0).toFixed(0);

  const _pillar = (label, emoji, score, dir, note) => {
    const n = (note||'').toString();
    return `<div class="ii-pillar">
      <div class="ii-pillar-header">
        <span class="ii-pillar-emoji">${emoji}</span>
        <span class="ii-pillar-label">${label}</span>
        <span class="ii-pillar-score" style="color:${scoreColor(score)}">${fmtI(score)}</span>
      </div>
      <div class="ii-pillar-dir ${dir === 'BULLISH' ? 'ii-bull' : dir === 'BEARISH' ? 'ii-bear' : 'ii-neut'}">${esc(dir.replace(/_/g,' '))}</div>
      <div class="ii-pillar-note">${esc(n.slice(0,130))}${n.length > 130 ? '…' : ''}</div>
    </div>`;
  };

  const evidence = (ii.evidence || []).slice(0, 5);
  const evHtml = evidence.length ? `
    <div class="ii-evidence">
      <div class="ii-what-label">Evidence Chain</div>
      ${evidence.map(e => `<div class="ii-evidence-row">
        <span class="ii-ev-src">${esc(e.source||'')}</span>
        <span class="ii-ev-dir ${e.direction==='BULLISH'?'ii-bull':e.direction==='BEARISH'?'ii-bear':'ii-neut'}">${esc(e.direction||'')}</span>
        <span class="ii-ev-str" style="color:var(--faint)">${esc(e.strength||'')}</span>
        <span class="ii-ev-note">${esc((e.note||'').slice(0,80))}${(e.note||'').length>80?'…':''}</span>
      </div>`).join('')}
    </div>` : '';

  el.innerHTML = `
    <div class="ii-overall">
      <div class="ii-score" style="color:${scoreColor(ii.overall_score||50)}">${fmtI(ii.overall_score||0)}</div>
      <div>
        <div class="ii-alignment" style="color:${alignColor}">${esc(alignment.replace(/_/g,' '))}</div>
        <div style="font-size:10px;color:${scoreColor(ii.overall_score||50)};font-family:var(--mono);font-weight:700">${esc(ii.institutional_bias||'')}</div>
      </div>
    </div>
    <div class="ii-read">${esc(ii.primary_read||ii.executive_summary||'')}</div>
    <div class="ii-pillar-grid">
      ${_pillar('Market Structure', '📊', msScore,   msDir,   msNote)}
      ${_pillar('Dealer',           '🏦', dScore,    dDir,    dNote)}
      ${_pillar('Institutional',    '🌊', instScore, instDir, instNote)}
      ${_pillar('Execution',        '⚡', execScore, execDir, execNote)}
    </div>
    <div class="ii-what">
      <div class="ii-what-label">What institutions are doing</div>
      <div class="ii-what-text">${esc(ii.what_institutions||'')}</div>
    </div>
    <div class="ii-what">
      <div class="ii-what-label">What dealers are doing</div>
      <div class="ii-what-text">${esc((ii.what_dealers||'').slice(0,250))}${(ii.what_dealers||'').length>250?'…':''}</div>
    </div>
    ${evHtml}
    ${ii.primary_risk ? `<div class="ii-what"><div class="ii-what-label" style="color:var(--red)">Primary Risk</div><div class="ii-what-text">${esc(ii.primary_risk)}</div></div>` : ''}
  `;
}

/* ── Ticker selector ──────────────────────────────────────────────────────── */
function initTickerSelect() {
  document.querySelectorAll('.ticker-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      activeTicker = btn.dataset.ticker;
      document.querySelectorAll('.ticker-btn').forEach(b => b.classList.toggle('active', b.dataset.ticker === activeTicker));
      loadOS();
      loadScannerIdeas();
    });
  });
}

/* ── Refresh button ───────────────────────────────────────────────────────── */
function initRefreshBtn() {
  const btn = $('refreshBtn');
  if (!btn) return;
  btn.addEventListener('click', async () => { await loadOS(); await loadScannerIdeas(); });
}

/* ════════════════════════════════════════════════════════════════════════════
   APEX 6.3.2 — Institutional Flow Tape
   ════════════════════════════════════════════════════════════════════════════ */
const TAPE_INDEX_TICKERS = new Set(['SPY','QQQ','SPX','SPXW']);
const TAPE_TECH_TICKERS  = new Set(['NVDA','TSLA','AAPL','MSFT','AMZN','META','GOOGL','AMD']);

let tapeFilter = 'all';
let tapeRows   = [];

function initTapeFilters() {
  document.querySelectorAll('.tape-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      tapeFilter = btn.dataset.filter || 'all';
      document.querySelectorAll('.tape-btn').forEach(b => b.classList.toggle('active', b.dataset.filter === tapeFilter));
      renderFlowTapeTable();
    });
  });
}

function filteredTapeRows() {
  if (tapeFilter === 'all')    return tapeRows;
  if (tapeFilter === 'SWEEP')  return tapeRows.filter(r => r.consolidation_type === 'SWEEP');
  if (tapeFilter === 'BLOCK')  return tapeRows.filter(r => r.consolidation_type === 'BLOCK');
  if (tapeFilter === 'index')  return tapeRows.filter(r => TAPE_INDEX_TICKERS.has(r.ticker));
  if (tapeFilter === 'tech')   return tapeRows.filter(r => TAPE_TECH_TICKERS.has(r.ticker));
  return tapeRows;
}

function fmtPremium(p) {
  if (!p && p !== 0) return '--';
  if (Math.abs(p) >= 1e6) return '$' + (p/1e6).toFixed(1) + 'M';
  if (Math.abs(p) >= 1e3) return '$' + (p/1e3).toFixed(0) + 'K';
  return '$' + p.toFixed(0);
}

function renderTapeSummary(summary) {
  const el = $('tapeSummaryBar');
  if (!el || !summary) return;
  const net = summary.net_premium || 0;
  const netCls = net >= 0 ? 'tape-sum-buy' : 'tape-sum-sell';
  el.innerHTML = `
    <div class="tape-sum-item"><span>Buy</span><b class="tape-sum-val tape-sum-buy">${fmtPremium(summary.buy_premium)}</b></div>
    <div class="tape-sum-item"><span>Sell</span><b class="tape-sum-val tape-sum-sell">${fmtPremium(summary.sell_premium)}</b></div>
    <div class="tape-sum-item"><span>Net</span><b class="tape-sum-val ${netCls}">${net >= 0?'+':''}${fmtPremium(net)}</b></div>
    <div class="tape-sum-item"><span>Sweeps</span><b class="tape-sum-val">${summary.sweep_count||0}</b></div>
    <div class="tape-sum-item"><span>Blocks</span><b class="tape-sum-val">${summary.block_count||0}</b></div>
    <div class="tape-sum-item"><span>Bias</span><b class="tape-sum-val ${summary.tape_bias==='BULLISH'?'tape-sum-buy':summary.tape_bias==='BEARISH'?'tape-sum-sell':''}">${esc(summary.tape_bias||'--')}</b></div>
  `;
}

function _formatContract(r) {
  // Format: SPX 7450C Jun30 or SPY 540P 06/28
  const ticker = r.ticker || '';
  const type   = r.contract_type === 'CALL' ? 'C' : r.contract_type === 'PUT' ? 'P' : '';
  const strike = r.strike ? Math.round(r.strike) : '';
  let exp = r.expiration || '';
  if (exp && exp.length === 10) {
    // YYYY-MM-DD → Jun30
    try {
      const d = new Date(exp + 'T12:00:00Z');
      const mo = d.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' });
      const dy = d.getUTCDate();
      exp = `${mo}${dy}`;
    } catch (_) { exp = exp.slice(5).replace('-','/'); }
  }
  return [ticker, `${strike}${type}`, exp].filter(Boolean).join(' ');
}

function renderFlowTapeTable() {
  const el = $('flowTapeTable');
  if (!el) return;
  const rows = filteredTapeRows();
  if (!rows.length) {
    el.innerHTML = '<div class="tape-empty">No flow tape rows match the current filter.</div>';
    return;
  }
  const rowHtml = rows.slice(0, 100).map(r => {
    const agCls    = r.aggressor_side === 'BUY' ? 'tape-row-buy' : r.aggressor_side === 'SELL' ? 'tape-row-sell' : 'tape-row-neutral';
    const label    = (r.tape_label || '--').replace(/_/g, ' ');
    const contract = _formatContract(r);
    const price    = r.trade_price ? fmt(r.trade_price) : '--';
    const imp      = r.importance_score != null ? r.importance_score : '';
    // Color the label badge
    const labelCls = r.aggressor_side === 'BUY' ? 'tape-label-buy' : r.aggressor_side === 'SELL' ? 'tape-label-sell' : 'tape-label-neut';
    return `<tr class="${agCls}">
      <td class="tape-td-time">${esc(r.time_et || '')}</td>
      <td class="tape-td-contract"><b>${esc(contract)}</b></td>
      <td class="tape-td-price">${price}</td>
      <td class="tape-td-premium"><b>${fmtPremium(r.premium)}</b></td>
      <td class="tape-td-label"><span class="tape-label ${labelCls}">${esc(label)}</span></td>
      <td class="tape-td-score">${imp}</td>
    </tr>`;
  }).join('');
  el.innerHTML = `<table>
    <thead><tr>
      <th>Time</th>
      <th>Contract</th>
      <th>Price</th>
      <th>Premium</th>
      <th>Type</th>
      <th>Score</th>
    </tr></thead>
    <tbody>${rowHtml}</tbody>
  </table>`;
}

async function loadFlowTape() {
  try {
    const r = await fetch('/api/flow_tape?tickers=SPY,QQQ,SPX,NVDA,TSLA&min_premium=100000', { cache: 'no-store' });
    if (!r.ok) return;
    const data = await r.json();
    if (!data.ok) return;
    tapeRows = data.rows || [];
    renderTapeSummary(data.summary);
    renderFlowTapeTable();
  } catch (e) {
    // Non-fatal: tape unavailable
    const el = $('flowTapeTable');
    if (el) el.innerHTML = '<div class="tape-empty">Flow tape unavailable: ' + esc(e.message) + '</div>';
  }
}

/* ════════════════════════════════════════════════════════════════════════════
   APEX 6.3.3 — Chart Overlay Toggle Wiring
   ════════════════════════════════════════════════════════════════════════════ */
function initOverlayToggles() {
  document.querySelectorAll('.overlay-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const group = btn.dataset.group;
      const nowActive = btn.classList.toggle('active');
      if (window.APEXOverlays) {
        window.APEXOverlays.setToggle(group, nowActive);
      }
      // Re-apply overlays on both chart engines if available
      try {
        const frame = document.querySelector('.chart-terminal-frame');
        if (frame && frame.contentWindow && frame.contentWindow.reapplyOverlays) {
          frame.contentWindow.reapplyOverlays();
        }
      } catch (_) {}
    });
  });
}

/* ════════════════════════════════════════════════════════════════════════════
   APEX 6.4.0 — Post-Trade Review Form
   ════════════════════════════════════════════════════════════════════════════ */
function initReviewForm() {
  const btn = $('rfSubmitBtn');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    const status = $('rfStatus');
    const payload = {
      ticker:         ($('rfTicker')?.value || 'SPX').toUpperCase(),
      side:           $('rfSide')?.value || 'CALL',
      entry_time:     $('rfEntryTime')?.value || '',
      exit_time:      $('rfExitTime')?.value || '',
      entry_price:    parseFloat($('rfEntryPrice')?.value) || null,
      exit_price:     parseFloat($('rfExitPrice')?.value) || null,
      contract:       $('rfContract')?.value || '',
      pnl:            parseFloat($('rfPnl')?.value) || null,
      reason_entered: $('rfReasonIn')?.value || '',
      reason_exited:  $('rfReasonOut')?.value || '',
      followed_plan:  parseInt($('rfFollowedPlan')?.value || '1'),
      mistakes:       $('rfMistakes')?.value || '',
      lesson:         $('rfLesson')?.value || '',
    };
    try {
      if (status) status.textContent = 'Saving...';
      const r = await fetch('/api/review/trade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await r.json();
      if (data.ok) {
        if (status) status.textContent = '✓ Saved trade #' + data.id;
        loadReviewSummary();
        loadTradeHistory();
      } else {
        if (status) status.textContent = 'Error: ' + (data.error || 'Unknown');
      }
    } catch (e) {
      if (status) status.textContent = 'Error: ' + e.message;
    }
  });
}

async function loadReviewSummary() {
  const el = $('reviewSummaryPanel');
  if (!el) return;
  try {
    const r = await fetch('/api/review/summary?ticker=' + activeTicker, { cache: 'no-store' });
    if (!r.ok) return;
    const data = await r.json();
    if (!data.ok) return;
    const s = data.summary || {};
    if (!data.trade_count) {
      el.innerHTML = '<div class="review-empty">No trades logged yet.</div>';
      return;
    }
    const wr = s.win_rate_pct ?? '--';
    const wrCls = (s.win_rate_pct >= 55) ? 'rs-green' : (s.win_rate_pct < 45) ? 'rs-red' : '';
    const arCls = (s.avg_r >= 1.0) ? 'rs-green' : 'rs-red';
    el.innerHTML = `
      <div class="review-summary-grid">
        <div class="rs-stat"><div class="rs-num ${wrCls}">${wr}%</div><div class="rs-label">Win Rate</div></div>
        <div class="rs-stat"><div class="rs-num ${s.avg_pnl>=0?'rs-green':'rs-red'}">${s.avg_pnl!=null?'$'+s.avg_pnl.toFixed(0):'--'}</div><div class="rs-label">Avg P&amp;L</div></div>
        <div class="rs-stat"><div class="rs-num ${arCls}">${s.avg_r!=null?s.avg_r+'R':'--'}</div><div class="rs-label">Avg R</div></div>
        <div class="rs-stat"><div class="rs-num">${data.trade_count}</div><div class="rs-label">Trades</div></div>
      </div>
      ${s.top_mistakes?.length ? `<div style="font-size:10px;color:var(--muted);margin-bottom:6px"><b>Common mistakes:</b> ${s.top_mistakes.slice(0,3).map(m=>`${esc(m.mistake)} (${m.count})`).join(', ')}</div>` : ''}
      ${s.recent_lessons?.length ? `<div style="font-size:10px;color:var(--faint)"><b>Lessons:</b> ${esc(s.recent_lessons[s.recent_lessons.length-1]||'')}</div>` : ''}
    `;
  } catch (_) {}
}

async function loadTradeHistory() {
  const el = $('reviewPanel');
  if (!el) return;
  try {
    const r = await fetch('/api/review/trades?ticker=' + activeTicker + '&limit=30', { cache: 'no-store' });
    if (!r.ok) return;
    const data = await r.json();
    if (!data.ok || !data.trades?.length) {
      el.innerHTML = '<div class="review-empty">No trade history yet.</div>';
      return;
    }
    const rowHtml = data.trades.map(t => {
      const pnlCls = (t.pnl || 0) >= 0 ? 'rv-green' : 'rv-red';
      return `<tr>
        <td>${esc(t.ticker)}</td>
        <td>${esc(t.side)}</td>
        <td>${esc(t.entry_time||'')}</td>
        <td>${esc(t.exit_time||'')}</td>
        <td>${t.entry_price!=null?'$'+t.entry_price.toFixed(2):'--'}</td>
        <td>${t.exit_price!=null?'$'+t.exit_price.toFixed(2):'--'}</td>
        <td class="${pnlCls}">${t.pnl!=null?'$'+t.pnl.toFixed(0):'--'}</td>
        <td>${t.followed_plan?'✓':'✗'}</td>
        <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis">${esc(t.reason_entered||'')}</td>
      </tr>`;
    }).join('');
    el.innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:11px;font-family:var(--mono)">
      <thead><tr style="font-size:9px;color:var(--faint)">
        <th style="text-align:left;padding:4px 6px">Ticker</th>
        <th>Side</th><th>In</th><th>Out</th>
        <th>Entry</th><th>Exit</th><th>P&amp;L</th><th>Plan</th><th>Reason</th>
      </tr></thead>
      <tbody>${rowHtml}</tbody>
    </table>`;
  } catch (_) {}
}

/* ════════════════════════════════════════════════════════════════════════════
   APEX 6.4.0 — Replay with date picker
   ════════════════════════════════════════════════════════════════════════════ */
function initReplayDatePicker() {
  const picker = $('replayDatePicker');
  const btn    = $('replayLoadBtn');
  if (!picker) return;
  // Set default to today
  const today = new Date();
  picker.value = today.toISOString().slice(0, 10);
  if (btn) {
    btn.addEventListener('click', async () => {
      const date = picker.value || today.toISOString().slice(0, 10);
      await loadReplaySession(date);
    });
  }
}

async function loadReplaySession(date) {
  try {
    const r = await fetch(`/api/replay/session?ticker=${activeTicker}&date=${date}`, { cache: 'no-store' });
    if (!r.ok) return;
    const data = await r.json();
    if (!data.ok) return;
    // Update the scrub bar
    const scrub = $('replayScrub');
    const time  = $('replayTime');
    const count = data.frame_count || 0;
    if (scrub) { scrub.min = 0; scrub.max = Math.max(0, count - 1); scrub.value = count - 1; }
    if (time) time.textContent = `${count} / ${count}`;
    // Load last frame
    if (count > 0 && data.frames?.length) {
      const lastFrame = data.frames[data.frames.length - 1];
      await loadReplayFrame(date, lastFrame.frame_time);
    }
  } catch (_) {}
}

async function loadReplayFrame(date, frameTime) {
  const el = $('replayFrame');
  if (!el) return;
  try {
    const r = await fetch(`/api/replay/frame?ticker=${activeTicker}&date=${date}&time=${frameTime}`, { cache: 'no-store' });
    if (!r.ok) return;
    const data = await r.json();
    if (!data.ok || !data.frame) {
      el.innerHTML = '<div class="rf-label">No replay frame available for that time.</div>';
      return;
    }
    const f = data.frame;
    const decCls = f.decision_state?.includes('ENTER') ? 'rv-green'
                 : f.decision_state === 'NO_TRADE'     ? 'rv-red'
                 : 'rv-amber';

    // Story snapshot — the key addition in 6.4.1
    const storyHtml = f.executive_summary
      ? `<div class="replay-story">${esc(f.executive_summary)}</div>`
      : '';

    // Coach snapshot
    const coachHtml = f.coach_action
      ? `<div class="replay-coach-action">${esc(f.coach_action)}</div>
         <div class="cmd-row"><span>Entry</span><b>${esc(f.coach_entry || '--')}</b></div>
         <div class="cmd-row"><span>Stop / T1 / T2</span><b>${f.coach_stop != null ? '$'+fmt(f.coach_stop) : '--'} / ${f.coach_t1 != null ? '$'+fmt(f.coach_t1) : '--'} / ${f.coach_t2 != null ? '$'+fmt(f.coach_t2) : '--'}</b></div>`
      : '';

    el.innerHTML = `
      <div class="rf-header">
        <div class="rf-label">${esc(date)} @ ${esc(data.frame_time || '')}</div>
        <div class="decision-badge ${decCls}" style="font-size:10px;padding:3px 8px">${esc(f.decision_state || '--')}</div>
      </div>
      ${storyHtml}
      <div class="replay-meta-grid">
        <div class="cmd-row"><span>ICI</span><b>${f.ici != null ? f.ici.toFixed(1) : '--'}</b></div>
        <div class="cmd-row"><span>Price</span><b>${f.stock_price != null ? '$' + fmt(f.stock_price) : '--'}</b></div>
        <div class="cmd-row"><span>POC</span><b>${f.poc != null ? '$' + fmt(f.poc) : '--'}</b></div>
        <div class="cmd-row"><span>vs POC / VA</span><b>${esc(f.price_vs_poc || '--')} / ${esc(f.price_vs_va || '--')}</b></div>
        <div class="cmd-row"><span>Migration</span><b>${esc(f.poc_migration || '--')}</b></div>
        <div class="cmd-row"><span>Auction</span><b>${esc(f.auction_state || '--')}</b></div>
        <div class="cmd-row"><span>Gamma</span><b>${esc(f.gamma_regime || '--')}${f.flip_risk ? ' ⚠ Flip' : ''}</b></div>
        <div class="cmd-row"><span>Flow / Tape</span><b>${esc(f.flow_bias || '--')} / ${esc(f.tape_bias || '--')}</b></div>
        <div class="cmd-row"><span>Pine</span><b>${esc(f.pine_state || '--')}${f.signal_secs ? ' (' + Math.floor(f.signal_secs/60) + 'm)' : ''}</b></div>
        <div class="cmd-row"><span>Grade</span><b>${esc(f.grade || '--')}</b></div>
      </div>
      ${coachHtml}
    `;
  } catch (_) {}
}

/* ════════════════════════════════════════════════════════════════════════════
   Market Status Banner
   ════════════════════════════════════════════════════════════════════════════ */

function renderMarketStatusBanner(status) {
  const el = $('marketStatusBanner');
  if (!el || !status) return;

  const level    = (status.level || 'RED').toLowerCase();
  const dotColor = { green: 'msb-dot-green', amber: 'msb-dot-amber', red: 'msb-dot-red' };
  const itemColor = { green: 'var(--green)', amber: 'var(--amber)', red: 'var(--red)' };

  const itemsHtml = (status.items || []).map(item => `
    <div class="msb-item">
      <div class="msb-dot ${dotColor[item.color] || 'msb-dot-red'}"></div>
      <div class="msb-item-text">
        <div class="msb-item-label">${esc(item.label)}</div>
        <div class="msb-item-status" style="color:${itemColor[item.color] || 'var(--red)'}">${esc(item.status)}</div>
        <div class="msb-item-detail">${esc(item.detail || '')}</div>
      </div>
    </div>`).join('');

  el.className = `market-status-banner msb-level-${level}`;
  el.innerHTML = `
    <div class="msb-header">
      <div class="msb-title">${esc(status.title || 'MARKET STATUS')}</div>
      <div class="msb-message">${esc(status.message || '')}</div>
      ${status.next_rth ? `<div class="msb-next">Next RTH: ${esc(status.next_rth)}</div>` : ''}
    </div>
    <div class="msb-items">${itemsHtml}</div>
  `;
  el.style.display = 'block';
}

async function loadMarketStatus() {
  try {
    const r = await fetch('/api/market_status', { cache: 'no-store' });
    if (!r.ok) return;
    const data = await r.json();
    if (data.ok) renderMarketStatusBanner(data);
  } catch (_) {}
}

/* ════════════════════════════════════════════════════════════════════════════
   Overnight Game Plan
   ════════════════════════════════════════════════════════════════════════════ */

function renderOvernightGamePlan(d) {
  const card    = $('overnightPlanCard');
  const content = $('overnightPlanContent');
  if (!card || !content || !d) return;

  const plan = d.overnight_game_plan;
  if (!plan) {
    card.style.display = 'none';
    return;
  }

  card.style.display = 'block';

  const bias = plan.bias || 'NEUTRAL';
  const biasCls = bias.includes('BULL') ? 'on-bias-bull' : bias.includes('BEAR') ? 'on-bias-bear' : 'on-bias-neut';
  const biasArrow = bias.includes('BULL') ? '▲' : bias.includes('BEAR') ? '▼' : '—';

  const levelsHtml = (plan.key_levels || []).map(l =>
    `<div class="on-level-chip">${esc(l.label)}: $${fmt(l.price)}</div>`
  ).join('');

  const statsHtml = [
    plan.overnight_high  ? `Overnight High: $${fmt(plan.overnight_high)}` : '',
    plan.overnight_low   ? `Overnight Low: $${fmt(plan.overnight_low)}`  : '',
    plan.overnight_range ? `Range: ${plan.overnight_range} pts`          : '',
    plan.projected_gap != null ? `Gap: ${plan.projected_gap > 0 ? '+' : ''}${plan.projected_gap.toFixed(2)} pts` : '',
  ].filter(Boolean).map(s => `<span class="on-level-chip">${esc(s)}</span>`).join('');

  content.innerHTML = `
    <div class="on-bias-badge ${biasCls}">${biasArrow} ${esc(bias.replace(/_/g,' '))} OVERNIGHT BIAS</div>
    <div class="on-exec">${esc(plan.executive_summary || '')}</div>
    <div class="on-game-plan">${esc(plan.game_plan || '')}</div>
    <div class="on-levels">${statsHtml}</div>
    ${levelsHtml ? `<div class="on-levels" style="margin-top:6px">${levelsHtml}</div>` : ''}
    <div style="margin-top:10px;font-size:10px;color:var(--faint);font-family:var(--mono)">
      ${plan.bars_used || 0} overnight bars · next RTH: ${esc(plan.next_rth || '9:30 AM ET')}
    </div>
  `;
}

/* ── Init ─────────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  initInnerTabs();
  initReplayControls();
  // DCC clock — update every second
  setInterval(() => {
    const clockEl = $('dccClock');
    if (clockEl) {
      const et = new Date().toLocaleString('en-US', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
      clockEl.textContent = et + ' ET';
    }
  }, 1000);
  initTickerSelect();
  initRefreshBtn();
  initRunScanButtons();
  initTapeFilters();
  initOverlayToggles();
  initReviewForm();
  initReplayDatePicker();

  // Activate first tab
  document.querySelector('.tab-btn[data-tab="dashboard"]')?.click();

  // Lazy-load chart iframe only when Chart tab is opened
  document.querySelector('.tab-btn[data-tab="chart"]')?.addEventListener('click', () => {
    const frame = $('chartTabFrame');
    if (frame && !frame.src) frame.src = '/chart';
  });

  loadOS();
  loadScannerIdeas();
  loadFlowTape();
  loadReviewSummary();
  loadTradeHistory();
  loadMarketStatus();
  loadSavedReviews();
  loadSignalLog();

  setInterval(loadOS, AUTO_INTERVAL);
  setInterval(loadScannerIdeas, 30000);
  setInterval(loadFlowTape, 45000);
  setInterval(loadMarketStatus, 60000);
  setInterval(loadSignalLog, 30000);
});

/* ════════════════════════════════════════════════════════════════════════════
   SPRINT 8 — DECISION COMMAND CENTER + CONFIDENCE PYRAMID
   Reads exclusively from institutional_intelligence + existing engine outputs.
   ════════════════════════════════════════════════════════════════════════════ */

/* ── Helpers ──────────────────────────────────────────────────────────────── */
function dccBiasColor(b) {
  return b === 'BULLISH' ? 'var(--green)' : b === 'BEARISH' ? 'var(--red)' : 'var(--muted)';
}
function dccStageColor(stage) {
  return stage === 'EXECUTE' ? 'var(--green)'  :
         stage === 'ARMED'   ? 'var(--amber)'  :
         stage === 'PREPARE' ? '#60a5fa'        : 'var(--faint)';
}
function dccDecisionClass(state) {
  if (!state) return 'dcc-neutral';
  if (state.startsWith('ENTER_CALL'))  return 'dcc-call';
  if (state.startsWith('ENTER_PUT'))   return 'dcc-put';
  if (state.startsWith('WATCH_CALL'))  return 'dcc-watch-call';
  if (state.startsWith('WATCH_PUT'))   return 'dcc-watch-put';
  if (state === 'READY')               return 'dcc-watch-call';
  return 'dcc-neutral';
}

/* ────────────────────────────────────────────────────────────────────────────
   renderDCC — Decision Command Center (Sprint 8.0.1)
   Reads from: institutional_intelligence, market_drivers, dealer_positioning,
               trade_coach, story, playbook, ribbon, ici
   ────────────────────────────────────────────────────────────────────────── */
function renderDCC(d) {
  if (!d) return;

  const ii    = (d.institutional_intelligence && d.institutional_intelligence.available)
                  ? d.institutional_intelligence : null;
  const tc    = d.trade_coach  || {};
  const ms    = d.market_state || d.ribbon || {};
  const rib   = d.ribbon || {};
  const story = d.story  || {};
  const ici   = d.ici    || {};
  const pb    = d.playbook || {};
  const dp    = d.dealer_positioning || {};
  const md    = d.market_drivers || {};

  const decision     = (ii && ii.decision_state)  || d.decision_state || 'NO_TRADE';
  const instBias     = (ii && ii.institutional_bias) || 'NEUTRAL';
  const dealerBias   = (ii && ii.delta_bias) || (dp.delta || {}).bias || 'NEUTRAL';
  const gammaRegime  = (ii && ii.gamma_regime) || (dp.gamma || {}).regime || 'NEUTRAL_GAMMA';
  const sessionState = (ii && ii.session_state) || d.session?.session_state || '';
  const iciScore     = Number((ici.ici) || 0);
  const pocMig       = (ii && ii.poc_migration) || ms.poc_migration || 'STABLE';
  const flowBias     = (ii && ii.flow_bias) || 'MIXED';
  const flowUrgency  = (ii && ii.flow_urgency) || 'LOW';
  const pineConf     = (ii && ii.pine_confirmed) || false;
  const pinProb      = Number((ii && ii.pin_probability) || 0);
  const momProb      = Number((ii && ii.momentum_probability) || 0);
  const acceptance   = (ii && ii.acceptance) || '';
  const auctionBias  = (ii && ii.auction_bias) || '';

  const price    = rib.spx_price || ms.price || 0;
  const esPrice  = rib.es_price  || 0;

  // ── Market Status Bar ────────────────────────────────────────────────────
  const marketStatEl   = $('dccMarketState');
  const sessionTypeEl  = $('dccSessionType');
  const dealerEnvEl    = $('dccDealerEnv');
  const instBiasEl     = $('dccInstBias');
  const priceEl        = $('dccPrice');
  const esEl           = $('dccES');

  if (marketStatEl) {
    const msl = sessionState === 'MARKET_OPEN' ? 'OPEN' :
                sessionState === 'PREMARKET'   ? 'PRE-MARKET' :
                sessionState === 'AFTER_HOURS' ? 'AFTER-HRS' :
                sessionState === 'OVERNIGHT'   ? 'OVERNIGHT' : 'CLOSED';
    marketStatEl.textContent = msl;
    marketStatEl.style.color = sessionState === 'MARKET_OPEN' ? 'var(--green)' : 'var(--amber)';
  }

  // Session type from playbook or fallback
  const pbSession = (pb.session_type || {}).type || '';
  if (sessionTypeEl) {
    sessionTypeEl.textContent = (pbSession || 'MONITORING').replace(/_/g, ' ');
    sessionTypeEl.style.color = pbSession === 'TREND_DAY' ? 'var(--green)' :
                                 pbSession === 'VOLATILE_DAY' ? 'var(--red)' :
                                 pbSession === 'PINNING_DAY' ? 'var(--amber)' : 'var(--muted)';
  }

  if (dealerEnvEl) {
    const denv = gammaRegime.replace('_GAMMA', '').replace('_', ' ');
    dealerEnvEl.textContent = denv;
    dealerEnvEl.style.color = gammaRegime === 'NEGATIVE_GAMMA' ? 'var(--red)' :
                               gammaRegime === 'POSITIVE_GAMMA' ? 'var(--green)' : 'var(--muted)';
  }
  if (instBiasEl) {
    instBiasEl.textContent = instBias;
    instBiasEl.style.color = dccBiasColor(instBias);
  }
  if (priceEl && price) priceEl.textContent = '$' + fmt(price);
  if (esEl && esPrice)  esEl.textContent    = '$' + fmt(esPrice);

  // Clock
  const clockEl = $('dccClock');
  if (clockEl) {
    const now = new Date();
    const et  = now.toLocaleString('en-US', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    clockEl.textContent = et + ' ET';
  }

  // ── Executive Summary ────────────────────────────────────────────────────
  const execEl = $('dccExecSummary');
  if (execEl) {
    // Prefer institutional_intelligence executive_summary, then story, then playbook
    const exec = (ii && ii.executive_summary) ||
                 story.executive_summary ||
                 (pb.primary_scenario || {}).path || '';

    if (sessionState === 'OVERNIGHT' || sessionState === 'PREMARKET') {
      const onPlan = d.overnight_game_plan || {};
      const onBias = onPlan.bias || 'NEUTRAL';
      const biasC  = onBias.includes('BULL') ? 'var(--green)' : onBias.includes('BEAR') ? 'var(--red)' : 'var(--amber)';
      execEl.innerHTML = `
        <div style="margin-bottom:6px">
          <span style="font-family:var(--mono);font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.08em;color:var(--faint)">
            ${sessionState === 'OVERNIGHT' ? '☾ OVERNIGHT' : '⊙ PRE-MARKET'}
          </span>
          <span style="margin-left:8px;font-family:var(--mono);font-size:11px;font-weight:800;color:${biasC}">${esc(onBias.replace(/_/g,' '))}</span>
        </div>
        <div class="dcc-exec-text-body">${esc(onPlan.executive_summary || exec || 'Building overnight context...')}</div>`;
    } else if (exec) {
      execEl.innerHTML = `<div class="dcc-exec-text-body">${esc(exec)}</div>`;
    } else {
      execEl.innerHTML = '<div class="sk-waiting">⌛ Loading institutional read...</div>';
    }
  }

  // ── Trade Decision + Execution Ring ──────────────────────────────────────
  const decEl   = $('dccDecision');
  const ringEl  = $('dccRingFill');
  const scoreEl = $('dccExecScore');
  const stageEl = $('dccExecStage');
  const stageDescEl = $('dccExecStageDesc');

  if (decEl) {
    decEl.textContent = decision.replace(/_/g, ' ');
    decEl.className   = 'dcc-decision-badge ' + dccDecisionClass(decision);
  }

  // Execution score and stage — prefer EIE engine, fall back to ICI
  const eie = d.execution_intelligence;
  const execScore = eie && eie.available ? Math.round(eie.exec_probability || 0) : Math.round(iciScore);
  const stage = eie && eie.stage ? eie.stage :
                execScore >= 90 ? 'EXECUTE' :
                execScore >= 75 ? 'ARMED'   :
                execScore >= 55 ? 'PREPARE' : 'WATCH';
  const stageColor = eie && eie.stage_color ? eie.stage_color : dccStageColor(stage);

  if (ringEl) {
    const circ = 213.6;
    const offset = circ * (1 - execScore / 100);
    ringEl.style.strokeDashoffset = offset.toString();
    ringEl.style.stroke = stageColor;
  }
  if (scoreEl) { scoreEl.textContent = execScore; scoreEl.style.color = stageColor; }
  if (stageEl) { stageEl.textContent = stage; stageEl.style.color = stageColor; }
  if (stageDescEl) {
    const stageDescs = {
      EXECUTE: 'All gates aligned — entry permitted',
      ARMED:   'Near entry — confirm Pine trigger',
      PREPARE: 'Conditions building — stay alert',
      WATCH:   'Monitoring — not ready to act',
    };
    stageDescEl.textContent = stageDescs[stage] || '';
  }

  // ── Why Bullets ───────────────────────────────────────────────────────────
  const whyEl    = $('dccWhyBullets');
  const whyLabel = $('dccWhyLabel');
  if (whyEl) {
    const isEnter = decision.startsWith('ENTER');
    const isWatch = decision.startsWith('WATCH') || decision === 'READY';
    if (whyLabel) {
      whyLabel.textContent = isEnter ? 'Enter Because' : isWatch ? 'Watching Because' : 'Blocked By';
      whyLabel.style.color = isEnter ? 'var(--green)' : isWatch ? 'var(--amber)' : 'var(--red)';
    }

    // Build evidence bullets from institutional_intelligence.evidence + gates
    const evidence = (ii && ii.evidence) || [];
    const bullets = [];

    // From evidence chain
    evidence.slice(0, 4).forEach(ev => {
      const ok = ev.direction === instBias || ev.direction === 'BULLISH' && instBias === 'BULLISH' || ev.direction === 'BEARISH' && instBias === 'BEARISH';
      bullets.push({ ok: ok && ev.strength !== 'LOW', label: ev.source.replace(/_/g, ' ') + ': ' + ev.note.slice(0, 55) });
    });

    // Append key gates
    bullets.push({ ok: pineConf,   label: 'Pine signal confirmed and fresh' });
    bullets.push({ ok: iciScore >= 70, label: `ICI ${fmtI(iciScore)}/100 — institutional alignment` });
    if (pocMig === 'RISING')  bullets.push({ ok: true,  label: 'POC migrating higher — value accepted' });
    if (pocMig === 'FALLING') bullets.push({ ok: true,  label: 'POC migrating lower — value accepted' });
    if (flowUrgency === 'HIGH') bullets.push({ ok: flowBias !== 'MIXED', label: 'High-urgency institutional sweeps' });
    if (!pineConf) bullets.push({ ok: false, label: 'Pine confirmation pending' });

    // Deduplicate, keep top 7
    const seen = new Set();
    const unique = bullets.filter(b => { const k = b.label.slice(0,30); if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 7);

    whyEl.innerHTML = unique.map(b => `
      <div class="dcc-why-row">
        <span class="dcc-why-dot ${b.ok ? 'dcc-dot-ok' : 'dcc-dot-no'}">${b.ok ? '✓' : '✗'}</span>
        <span class="dcc-why-text ${b.ok ? 'dcc-why-ok' : 'dcc-why-no'}">${esc(b.label)}</span>
      </div>`).join('');
  }

  // ── Invalidation ─────────────────────────────────────────────────────────
  const invEl = $('dccInvalidation');
  if (invEl) {
    const inv = (pb && pb.invalidation) ||
                (ii && ii.primary_risk)  ||
                (tc && tc.invalidation)  ||
                'Monitoring for changes in flow, POC direction, or dealer positioning.';
    invEl.textContent = inv;
  }

  // ── Confidence Pyramid ────────────────────────────────────────────────────
  renderConfidencePyramid(d, ii);
}

/* ────────────────────────────────────────────────────────────────────────────
   renderConfidencePyramid — Sprint 8.1 Trust Layer
   Shows which layer of the stack produced (or failed) the confidence score.
   ────────────────────────────────────────────────────────────────────────── */
function renderConfidencePyramid(d, ii) {
  const el = $('dccConfidencePyramid');
  if (!el) return;

  const ici    = d.ici || {};
  const comps  = ici.components || {};
  const wts    = ici.weights    || {};
  const rib    = d.ribbon || {};
  const dp     = d.dealer_positioning || {};
  const md     = d.market_drivers || {};
  const ms     = d.market_state || {};

  // Six pyramid layers, top to bottom (trade → foundational)
  const layers = [
    {
      label: 'Trade',
      score: Math.round(Number(ici.ici || 0)),
      note:  'Final execution score',
      source: 'ICI',
    },
    {
      label: 'Dealer Position',
      score: Math.round(Number((dp.gamma || {}).score || (dp.delta || {}).confidence || 50)),
      note:  `${((dp.gamma || {}).regime || 'NEUTRAL').replace(/_/g,' ')} · Delta ${(dp.delta || {}).bias || '--'}`,
      source: 'DEALER',
    },
    {
      label: 'Institutional Flow',
      score: Math.round(Number((ii && ii.flow_conviction) || comps.flow_momentum || 50)),
      note:  `${(ii && ii.flow_bias) || '--'} bias · ${(ii && ii.flow_urgency) || '--'} urgency`,
      source: 'FLOW',
    },
    {
      label: 'Auction / Volume',
      score: Math.round(Number(comps.conviction || 50)),
      note:  `${(ii && ii.auction_state) || '--'} · POC ${(ii && ii.poc_migration) || '--'}`,
      source: 'AUCTION',
    },
    {
      label: 'Market Structure',
      score: Math.round(Number(comps.gamma_stability || 50)),
      note:  `GEX ${Math.round(Number((dp.gamma || {}).gex_score || 50))} · ${(ii && ii.vol_regime) || '--'} vol`,
      source: 'STRUCTURE',
    },
    {
      label: 'Market Drivers',
      score: Math.round(Number((md.driver_score) || 50)),
      note:  `${(md.leadership_label || '--')} · ${(md.breadth || 'MIXED').replace(/_/g,' ')}`,
      source: 'DRIVERS',
    },
  ];

  const barColor = s => s >= 75 ? 'var(--green)' : s >= 55 ? 'var(--blue)' : s >= 40 ? 'var(--amber)' : 'var(--red)';

  // Pyramid renders top-to-bottom, widest at bottom (foundational)
  // Invert: Trade is apex (narrow), Drivers is base (wide)
  const layerCount = layers.length;

  el.innerHTML = layers.map((lyr, i) => {
    // Width: apex narrow (60%), base full (100%)
    const pct  = Math.round(60 + (i / (layerCount - 1)) * 40);
    const bc   = barColor(lyr.score);
    const weak = lyr.score < 50;
    return `
      <div class="pyr-layer" style="width:${pct}%">
        <div class="pyr-header">
          <span class="pyr-label ${weak ? 'pyr-weak' : ''}">${esc(lyr.label)}</span>
          <span class="pyr-score" style="color:${bc}">${lyr.score}</span>
        </div>
        <div class="pyr-bar-track">
          <div class="pyr-bar-fill" style="width:${lyr.score}%;background:${bc}"></div>
        </div>
        <div class="pyr-note">${esc(lyr.note)}</div>
      </div>`;
  }).join('');
}

/* ────────────────────────────────────────────────────────────────────────────
   renderMarketDriversPanel — Sprint 8.0.3
   Reads from: market_drivers (from /api/institutional_os)
   ────────────────────────────────────────────────────────────────────────── */
function renderMarketDriversPanel(d) {
  const el = $('marketDriversPanel');
  if (!el || !d) return;

  const md = d.market_drivers;
  if (!md || !md.available) {
    el.innerHTML = '<div class="sk-waiting">⌛ Fetching constituent data...</div>';
    return;
  }

  const biasColor = md.market_bias === 'BULLISH' ? 'var(--green)' :
                    md.market_bias === 'BEARISH'  ? 'var(--red)'   : 'var(--muted)';

  const bull = (md.top_bullish_drivers || []).slice(0, 4);
  const bear = (md.top_bearish_drivers || []).slice(0, 2);

  el.innerHTML = `
    <div class="md-header">
      <span class="md-bias" style="color:${biasColor}">${esc(md.market_bias||'MIXED')}</span>
      <span class="md-breadth">${esc((md.breadth||'').replace(/_/g,' '))}</span>
    </div>
    <div class="md-leadership">${esc(md.leadership_label||'')}</div>
    <div class="md-narrative">${esc(md.story_line||md.interpretation||'')}</div>
    ${bull.length ? `
    <div class="md-section-label">▲ Leading</div>
    ${bull.map(dr => `
      <div class="md-driver-row">
        <span class="md-ticker">${esc(dr.ticker)}</span>
        <span class="md-chg ${dr.change_pct>=0?'md-bull':'md-bear'}">${dr.change_pct>=0?'+':''}${(dr.change_pct||0).toFixed(2)}%</span>
        <div class="md-impact-bar-wrap">
          <div class="md-impact-bar" style="width:${Math.min(Math.abs(dr.weighted_impact||0)*8,100)}%;background:${dr.change_pct>=0?'var(--green)':'var(--red)'}"></div>
        </div>
        <span class="md-pts">${dr.change_pct>=0?'+':''}${(dr.weighted_impact||0).toFixed(1)}pt</span>
      </div>`).join('')}` : ''}
    ${bear.length ? `
    <div class="md-section-label" style="color:var(--red)">▼ Dragging</div>
    ${bear.map(dr => `
      <div class="md-driver-row">
        <span class="md-ticker">${esc(dr.ticker)}</span>
        <span class="md-chg md-bear">${(dr.change_pct||0).toFixed(2)}%</span>
        <div class="md-impact-bar-wrap">
          <div class="md-impact-bar" style="width:${Math.min(Math.abs(dr.weighted_impact||0)*8,100)}%;background:var(--red)"></div>
        </div>
        <span class="md-pts">${(dr.weighted_impact||0).toFixed(1)}pt</span>
      </div>`).join('')}` : ''}
    <div class="md-net">Net impact: <b>${(md.net_index_impact_pts||0)>=0?'+':''}${(md.net_index_impact_pts||0).toFixed(1)} pts</b></div>`;
}

/* ────────────────────────────────────────────────────────────────────────────
   renderStrikeMagnetPanel — Sprint 8.0.5
   Reads from: strike_magnets
   ────────────────────────────────────────────────────────────────────────── */
function renderStrikeMagnetPanel(d) {
  const el = $('strikeMagnetPanel');
  if (!el || !d) return;

  const sm = d.strike_magnets;
  if (!sm || !sm.available) {
    el.innerHTML = '<div class="sk-waiting">⌛ Building magnet map...</div>';
    return;
  }

  const pinColor = sm.pin_risk === 'HIGH' ? 'var(--amber)' : sm.pin_risk === 'MEDIUM' ? 'var(--blue)' : 'var(--faint)';
  const magnets  = (sm.magnets || []).slice(0, 5);
  const price    = sm.price || 0;

  el.innerHTML = `
    <div class="sm-pin-row">
      <span class="sm-pin-label">Pin Risk</span>
      <span class="sm-pin-val" style="color:${pinColor}">${esc(sm.pin_risk||'--')}</span>
    </div>
    ${sm.max_pain ? `<div class="sm-maxpain">Max Pain ~$${fmt(sm.max_pain)} <span class="sm-est">(est.)</span></div>` : ''}
    <div class="sm-magnets">
      ${magnets.map(m => {
        const above = m.side === 'ABOVE';
        const mc    = m.type === 'CALL_WALL' ? 'var(--green)' :
                      m.type === 'PUT_WALL'  ? 'var(--red)'   :
                      m.type === 'ZERO_GAMMA'? 'var(--amber)'  :
                      m.type === 'MAX_PAIN'  ? 'var(--purple)' : 'var(--faint)';
        const dist  = Math.abs(m.distance||0).toFixed(2);
        return `<div class="sm-row ${m.type === 'CALL_WALL' || m.type === 'PUT_WALL' ? 'sm-row-major' : ''}">
          <span class="sm-strike" style="color:${mc}">$${fmt(m.strike)}</span>
          <span class="sm-type">${esc((m.type||'').replace(/_/g,' '))}</span>
          <span class="sm-dist" style="color:${above?'var(--green)':'var(--red)'}">${above?'↑':'↓'}${dist}</span>
          <div class="sm-score-bar"><div style="width:${m.score||0}%;background:${mc}"></div></div>
        </div>`}).join('')}
    </div>
    <div class="sm-watch">${esc((sm.watch||'').slice(0,100))}</div>`;
}

/* ────────────────────────────────────────────────────────────────────────────
   renderFlowMeter — Sprint 8.0.4
   Reads from: flow_intelligence_2 inside the API response
   ────────────────────────────────────────────────────────────────────────── */
function renderFlowMeter(d) {
  const el = $('opFlowPanel');
  if (!el || !d) return;

  const fi = d.flow_intelligence_2 || d.flow_intelligence || d.flow || {};
  const ms = d.market_state || {};

  const bias      = fi.flow_bias || fi.bias || ms.flow_bias || 'MIXED';
  const conv      = Number(fi.flow_conviction || fi.conviction || 50);
  const urgency   = fi.urgency || 'LOW';
  const intent    = fi.flow_intent || fi.institutional_intent || 'MIXED';
  const swPress   = Number(fi.sweep_pressure || 0);
  const blkConv   = Number(fi.block_conviction || 0);
  const splitAcc  = Number(fi.split_accumulation || 0);
  const dealResp  = Number(fi.dealer_response || 50);
  const netPrem   = Number(fi.net_premium || ms.net_premium || 0);
  const callPrem  = Number(fi.call_premium || ms.call_premium || 0);
  const putPrem   = Number(fi.put_premium  || ms.put_premium  || 0);
  const sweeps    = Number(fi.sweep_count  || ms.tape_sweeps  || 0);
  const narrative = fi.narrative || fi.interpretation || '';
  const contras   = fi.contradictions || [];
  const dpLine    = fi.dark_pool_line || '';
  const dealRead  = fi.dealer_read    || '';

  const biasColor = bias === 'BULLISH' ? 'var(--green)' : bias === 'BEARISH' ? 'var(--red)' : 'var(--muted)';
  const urgColor  = urgency === 'HIGH' ? 'var(--amber)' : urgency === 'MEDIUM' ? 'var(--blue)' : 'var(--faint)';
  const barColor  = s => s >= 70 ? 'var(--green)' : s >= 45 ? 'var(--blue)' : 'var(--red)';

  const _meter = (label, score, hint) => `
    <div class="fm-meter">
      <div class="fm-meter-header">
        <span class="fm-meter-label">${label}</span>
        <span class="fm-meter-score" style="color:${barColor(score)}">${Math.round(score)}</span>
      </div>
      <div class="fm-meter-track"><div class="fm-meter-fill" style="width:${score}%;background:${barColor(score)}"></div></div>
      ${hint ? `<div class="fm-meter-hint">${esc(hint)}</div>` : ''}
    </div>`;

  el.innerHTML = `
    <div class="fm-header">
      <span class="fm-bias" style="color:${biasColor}">${esc(bias)}</span>
      <span class="fm-urgency" style="color:${urgColor}">${esc(urgency)} URGENCY</span>
      <span class="fm-intent">${esc(intent.replace(/_/g,' '))}</span>
    </div>

    ${_meter('Sweep Pressure',    swPress,  sweeps > 0 ? sweeps + ' active sweep' + (sweeps>1?'s':'') : '')}
    ${_meter('Block Conviction',  blkConv,  '')}
    ${_meter('Split Accumulation',splitAcc, '')}
    ${_meter('Dealer Response',   dealResp, '')}

    <div class="fm-prems">
      <div class="fm-prem-row"><span class="fm-prem-label">Call premium</span><span class="fm-prem-val rv-green">$${fmtM(callPrem)}</span></div>
      <div class="fm-prem-row"><span class="fm-prem-label">Put premium</span><span class="fm-prem-val rv-red">$${fmtM(putPrem)}</span></div>
      <div class="fm-prem-row"><span class="fm-prem-label">Net</span><span class="fm-prem-val" style="color:${netPrem>=0?'var(--green)':'var(--red)'}">${netPrem>=0?'+':''}$${fmtM(netPrem)}</span></div>
    </div>

    ${narrative ? `<div class="fm-narrative">${esc(narrative.slice(0,180))}</div>` : ''}
    ${contras.length ? `<div class="fm-contra">⚡ ${esc(contras[0].slice(0,120))}</div>` : ''}
    ${dpLine    ? `<div class="fm-dp">${esc(dpLine)}</div>` : ''}
    ${dealRead  ? `<div class="fm-dealer-read">${esc(dealRead.slice(0,100))}</div>` : ''}
  `;
}

/* ════════════════════════════════════════════════════════════════════════════
   EXECUTION INTELLIGENCE ENGINE — Sprint 8.0 Dashboard Panel
   Answers: "Is NOW the highest-probability moment to enter?"
   ════════════════════════════════════════════════════════════════════════════ */

function renderEIE(d) {
  const el = $('executionPanel');
  if (!el || !d) return;

  const eie = d.execution_intelligence;
  if (!eie || !eie.available) {
    el.innerHTML = `
      <div class="eie-loading">
        <div class="eie-trigger eie-not-ready">NOT READY</div>
        <div class="sk-waiting" style="margin-top:10px">⌛ Execution engine initializing...<br>
        <span style="font-size:10px;color:var(--faint)">Populates after first scan cycle. Requires market to be open.</span></div>
      </div>`;
    return;
  }

  const prob   = Number(eie.exec_probability || 0);
  const stage  = eie.stage || 'WATCH';
  const sc     = eie.stage_color || '#64748b';
  const timing = eie.timing || 'EARLY';
  const tc     = eie.timing_color || '#64748b';
  const trigger = eie.trigger_active || false;
  const tLabel  = eie.trigger_label  || 'NOT READY';
  const tColor  = eie.trigger_color  || '#64748b';

  // Ring fill
  const circ   = 201.1;  // 2π × 32
  const offset = circ * (1 - prob / 100);

  // Module scores
  const scores = eie.scores || {};
  const m1 = eie.pressure_acceleration || {};
  const m3 = eie.absorption || {};
  const m4 = eie.exhaustion || {};
  const m5 = eie.delta_acceleration || {};
  const m6 = eie.auction_acceptance  || {};
  const m7 = eie.gamma_wall || {};

  const barC = s => Number(s) >= 75 ? 'var(--green)' : Number(s) >= 55 ? 'var(--blue)' : Number(s) >= 40 ? 'var(--amber)' : 'var(--red)';
  const _bar = (label, score, note) => `
    <div class="eie-module">
      <div class="eie-mod-header">
        <span class="eie-mod-label">${label}</span>
        <span class="eie-mod-score" style="color:${barC(score)}">${Math.round(Number(score))}</span>
      </div>
      <div class="eie-mod-track"><div class="eie-mod-fill" style="width:${Math.min(Number(score)||0,100)}%;background:${barC(score)}"></div></div>
      ${note ? `<div class="eie-mod-note">${esc(note)}</div>` : ''}
    </div>`;

  // Why bullets
  const bullets = eie.why_bullets || [];

  // Timing badge
  const timingLabel = { PERFECT: '✦ PERFECT', GOOD: '✓ GOOD', EARLY: '◷ EARLY', LATE: '◷ LATE', MISSED: '✗ MISSED' };
  const timingClass = { PERFECT: 'eie-t-perfect', GOOD: 'eie-t-good', EARLY: 'eie-t-early', LATE: 'eie-t-late', MISSED: 'eie-t-missed' };

  el.innerHTML = `
    <!-- ── Institutional Trigger (hero) ──────────────────────────────────── -->
    <div class="eie-hero">
      <!-- Ring -->
      <div class="eie-ring-wrap">
        <svg class="eie-ring" viewBox="0 0 80 80">
          <circle class="eie-ring-bg"   cx="40" cy="40" r="32"/>
          <circle class="eie-ring-fill" cx="40" cy="40" r="32"
            stroke="${sc}"
            stroke-dasharray="${circ}" stroke-dashoffset="${offset}"
            style="transition:stroke-dashoffset .6s,stroke .3s"/>
        </svg>
        <div class="eie-ring-inner">
          <div class="eie-ring-prob"  style="color:${sc}">${Math.round(prob)}</div>
          <div class="eie-ring-label" style="color:${sc}">%</div>
        </div>
      </div>

      <!-- Trigger + Stage -->
      <div class="eie-trigger-col">
        <div class="eie-trigger" style="color:${tColor};border-color:${tColor};background:${tColor}18">${esc(tLabel)}</div>
        <div class="eie-stage"   style="color:${sc}">${esc(stage)}</div>
        <div class="eie-stage-desc">${esc(eie.stage_description||'')}</div>
        <div class="eie-timing ${timingClass[timing]||'eie-t-early'}">${timingLabel[timing]||timing}</div>
      </div>
    </div>

    <div class="eie-narrative">${esc(eie.narrative||'')}</div>

    <!-- ── Why bullets ─────────────────────────────────────────────────── -->
    ${bullets.length ? `
    <div class="eie-bullets">
      ${bullets.map(b => `
        <div class="eie-bullet-row">
          <span class="eie-bullet-dot ${b.ok?'eie-ok':'eie-no'}">${b.ok?'✓':'✗'}</span>
          <span class="eie-bullet-label ${b.ok?'eie-ok':'eie-no'}">${esc(b.label||b.text||'')}</span>
          <span class="eie-bullet-note">${esc(b.note||'')}</span>
        </div>`).join('')}
    </div>` : ''}

    <!-- ── Module scores ───────────────────────────────────────────────── -->
    <div class="eie-modules">
      ${_bar('Pressure Acceleration', scores.pressure   || m1.score||50, (m1.note||'').slice(0,60))}
      ${_bar('Liquidity Absorption',  scores.absorption || m3.score||50, m3.status||'')}
      ${_bar('Auction Acceptance',    scores.auction_acceptance || m6.score||50, m6.state_label||'')}
      ${_bar('Gamma Wall',            scores.gamma_wall || m7.score||50, (m7.interaction||'').replace(/_/g,' '))}
      ${_bar('Delta Acceleration',    m5.score||50, (m5.direction||'').replace(/_/g,' '))}
      ${_bar('Execution',             scores.execution  || prob, 'Composite execution score')}
    </div>

    <!-- ── Key module reads ─────────────────────────────────────────────── -->
    <div class="eie-reads">
      ${m4.state ? `<div class="eie-read-row"><span class="eie-read-label">Exhaustion</span><span class="eie-read-val" style="color:${m4.state==='BALANCED'?'var(--muted)':m4.state.includes('BUYER')?'var(--amber)':'var(--amber)'}">${esc(m4.state.replace(/_/g,' '))}</span></div>` : ''}
      ${m7.wall_at ? `<div class="eie-read-row"><span class="eie-read-label">Wall Interaction</span><span class="eie-read-val">$${fmt(m7.wall_at)} — ${esc((m7.interaction||'').replace(/_/g,' '))}</span></div>` : ''}
      ${m1.direction ? `<div class="eie-read-row"><span class="eie-read-label">Pressure</span><span class="eie-read-val">${esc((m1.direction||'').replace(/_/g,' '))}</span></div>` : ''}
    </div>

    <!-- ── Invalidation ─────────────────────────────────────────────────── -->
    ${eie.invalidation ? `
    <div class="eie-invalidation">
      <div class="eie-inv-label">Invalidation</div>
      <div class="eie-inv-text">${esc(eie.invalidation)}</div>
    </div>` : ''}
  `;
}

// Wire EIE into loadOS and refresh cycle

/* ════════════════════════════════════════════════════════════════════════════
   WORKSPACE — Six-Zone Professional Trading Layout (Sprint 9.0)
   Reads from: institutional_intelligence, execution_intelligence, trade_coach,
               dealer_positioning, market_drivers, flow_intelligence_2
   ════════════════════════════════════════════════════════════════════════════ */

/* Execution timeline history — persisted in-session */
const _wsTLHistory = [];
let   _wsLastStage = '';
let   _wsLastScore = 0;

function renderWorkspace(d) {
  if (!d) return;

  const ii  = (d.institutional_intelligence && d.institutional_intelligence.available) ? d.institutional_intelligence : null;
  const eie = (d.execution_intelligence && d.execution_intelligence.available)         ? d.execution_intelligence     : null;
  const tc  = d.trade_coach   || {};
  const dp  = d.dealer_positioning || {};
  const md  = d.market_drivers     || {};
  const ms  = d.market_state       || d.ribbon || {};
  const fi  = d.flow_intelligence_2 || d.flow || {};
  const ici = d.ici || {};
  const pb  = d.playbook || {};

  const execScore   = eie ? eie.exec_probability : Number(ici.ici || 0);
  const stage       = eie ? eie.stage : (execScore >= 90 ? 'EXECUTE' : execScore >= 75 ? 'ARMED' : execScore >= 55 ? 'PREPARE' : 'WATCH');
  const stageColor  = eie ? (eie.stage_color || '#64748b') :
    (stage === 'EXECUTE' ? '#22c55e' : stage === 'ARMED' ? '#f59e0b' : stage === 'PREPARE' ? '#60a5fa' : '#64748b');
  const decision    = (ii && ii.decision_state) || d.decision_state || 'NO_TRADE';
  const instBias    = (ii && ii.institutional_bias) || 'NEUTRAL';
  const dealerBias  = (ii && ii.delta_bias) || 'NEUTRAL';
  const gammaR      = (ii && ii.gamma_regime) || 'NEUTRAL_GAMMA';
  const flowBias    = (ii && ii.flow_bias) || 'MIXED';
  const pocMig      = (ii && ii.poc_migration) || 'STABLE';
  const acceptance  = (ii && ii.acceptance) || '';
  const price       = Number(ms.spx_price || ms.price || (d.ribbon || {}).spx_price || 0);
  const sessionSt   = (ii && ii.session_state) || '';

  // ── Zone 1: Execution Gauge ──────────────────────────────────────────────
  const scoreEl = $('wsExecScore');
  const stageEl = $('wsExecStage');
  const subEl   = $('wsGaugeSub');
  const fillEl  = $('wsGaugeFill');
  const biasEl  = $('wsBias');
  const agrEl   = $('wsAgreement');
  const confEl  = $('wsConfidence');

  if (scoreEl) { scoreEl.textContent = Math.round(execScore); scoreEl.style.color = stageColor; }
  if (stageEl) { stageEl.textContent = stage; stageEl.style.color = stageColor; }
  if (subEl) {
    const subMap = { EXECUTE: 'Pull the trigger', ARMED: 'Align final trigger', PREPARE: 'Conditions building', WATCH: 'Monitoring' };
    subEl.textContent = eie ? (eie.stage_description || subMap[stage] || '') : subMap[stage] || '';
  }
  if (fillEl) {
    const circ = 439.8; // 2π × 70 (new op-gauge r=70)
    fillEl.style.strokeDashoffset = (circ * (1 - execScore / 100)).toString();
    fillEl.style.stroke = stageColor;
    // Pulse on increase
    if (execScore > _wsLastScore) {
      fillEl.closest('svg') && fillEl.closest('svg').classList.add('op-gauge-pulsing');
      setTimeout(() => fillEl.closest('svg') && fillEl.closest('svg').classList.remove('op-gauge-pulsing'), 800);
    }
  }
  _wsLastScore = execScore;

  // Bias label
  const biasLabel = decision.startsWith('ENTER_CALL') || decision.startsWith('WATCH_CALL') ? 'CALLS' :
                    decision.startsWith('ENTER_PUT')  || decision.startsWith('WATCH_PUT')  ? 'PUTS'  :
                    decision === 'READY' ? 'READY' : instBias === 'NEUTRAL' ? 'WAIT' : 'NO TRADE';
  const biasColor = biasLabel === 'CALLS' ? 'var(--green)' : biasLabel === 'PUTS' ? 'var(--red)' : 'var(--faint)';
  if (biasEl) { biasEl.textContent = biasLabel; biasEl.style.color = biasColor; }

  // Agreement count
  const evidence = (ii && ii.evidence) || [];
  const bullSig  = (ii && ii.bull_signals) || evidence.filter(e => e.direction === 'BULLISH').length;
  const bearSig  = (ii && ii.bear_signals) || evidence.filter(e => e.direction === 'BEARISH').length;
  const totalEng = 7;
  const agreeCount = Math.min(totalEng, Math.max(bullSig, bearSig));
  if (agrEl) agrEl.textContent = `${agreeCount}/${totalEng} engines aligned`;
  if (confEl) {
    const conf = Math.round(Number((ii && ii.overall_score) || execScore));
    confEl.textContent = `${conf}% confidence`;
    confEl.style.color = conf >= 75 ? 'var(--green)' : conf >= 55 ? 'var(--amber)' : 'var(--faint)';
  }

  // Status strip
  const setWS = (id, text, color) => { const el = $(id); if (el) { el.textContent = text; if (color) el.style.color = color; } };
  setWS('wsMarket',    sessionSt === 'MARKET_OPEN' ? 'OPEN' : sessionSt.replace(/_/g,' '), sessionSt === 'MARKET_OPEN' ? 'var(--green)' : 'var(--amber)');
  setWS('wsSessionType', (d.playbook && d.playbook.session_type && d.playbook.session_type.type || sessionSt || '--').replace(/_/g,' '), '');
  setWS('wsInstBias', instBias, instBias === 'BULLISH' ? 'var(--green)' : instBias === 'BEARISH' ? 'var(--red)' : 'var(--faint)');
  setWS('wsDealer', (gammaR || 'NEUTRAL').replace('_GAMMA','').replace('_',' '), gammaR === 'NEGATIVE_GAMMA' ? 'var(--red)' : gammaR === 'POSITIVE_GAMMA' ? 'var(--green)' : 'var(--muted)');
  setWS('wsPOC',   pocMig === 'RISING' ? '▲ Rising' : pocMig === 'FALLING' ? '▼ Falling' : '— Stable', pocMig === 'RISING' ? 'var(--green)' : pocMig === 'FALLING' ? 'var(--red)' : 'var(--faint)');
  setWS('wsFlow',  flowBias, flowBias === 'BULLISH' ? 'var(--green)' : flowBias === 'BEARISH' ? 'var(--red)' : 'var(--faint)');
  setWS('wsGamma', (gammaR || '--').replace(/_/g,' ').replace('GAMMA','').trim() || 'NEUTRAL', '');
  setWS('wsPrice', price > 0 ? '$' + fmt(price) : '--', 'var(--blue)');

  // ── Zone 2: Institutional Consensus ──────────────────────────────────────
  const consEl = $('wsConsensus');
  if (consEl) {
    const engines = [
      { label: 'Market Regime', ok: instBias !== 'NEUTRAL', note: instBias },
      { label: 'Gamma',         ok: gammaR !== 'NEUTRAL_GAMMA', note: gammaR.replace(/_/g,' ').replace('GAMMA','').trim() },
      { label: 'Flow',          ok: flowBias !== 'MIXED',  note: flowBias },
      { label: 'Auction',       ok: acceptance === 'ACCEPTING' || pocMig !== 'STABLE', note: acceptance || pocMig },
      { label: 'Dealer',        ok: dealerBias !== 'NEUTRAL', note: dealerBias + ' delta' },
      { label: 'ICI',           ok: Number(ici.ici || 0) >= 60, note: fmtI(Number(ici.ici || 0)) + '/100' },
      { label: 'Risk',          ok: !(ii && ii.primary_risk && ii.primary_risk.startsWith('Excess')), note: 'Approved' },
    ];
    const agreeTotal = engines.filter(e => e.ok).length;
    consEl.innerHTML = engines.map(e => `
      <div class="op-eng-row ${e.ok ? 'op-eng-ok' : 'op-eng-no'}">
        <span class="op-eng-check">${e.ok ? '✔' : '✗'}</span>
        <span class="op-eng-label">${e.label}</span>
        <span class="op-eng-note">${esc(e.note || '')}</span>
      </div>`).join('');
    if (agreeTotal < 4 && !consEl.querySelector('.ws-no-trade-warn')) {
      consEl.innerHTML += `<div class="op-no-trade-warn">Only ${agreeTotal}/7 aligned — no trade.</div>`;
    }
  }

  // ── Zone 3: Execution Timeline ────────────────────────────────────────────
  // Stage step highlights
  const stageOrder = ['WATCH', 'PREPARE', 'ARMED', 'EXECUTE'];
  const stageColors = { WATCH: '#60a5fa', PREPARE: '#fbbf24', ARMED: '#f59e0b', EXECUTE: '#22c55e' };
  stageOrder.forEach(s => {
    const dotEl = $('wsStep' + s.charAt(0) + s.slice(1).toLowerCase());
    if (dotEl) {
      const active = stageOrder.indexOf(s) <= stageOrder.indexOf(stage);
      dotEl.style.background = active ? stageColors[s] : 'rgba(100,116,139,.15)';
      dotEl.style.boxShadow  = s === stage ? `0 0 8px ${stageColors[s]}` : 'none';
    }
  });

  // Add timeline entry when stage changes
  const now_str = new Date().toLocaleString('en-US', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false });
  if (stage !== _wsLastStage) {
    _wsTLHistory.unshift({ time: now_str, stage, score: Math.round(execScore), color: stageColors[stage] || '#64748b' });
    if (_wsTLHistory.length > 12) _wsTLHistory.pop();
    _wsLastStage = stage;
  }
  const feedEl = $('wsTimelineFeed');
  if (feedEl && _wsTLHistory.length) {
    feedEl.innerHTML = _wsTLHistory.map(h => `
      <div class="op-tl-entry">
        <span class="op-tl-time">${h.time}</span>
        <span class="op-tl-stage" style="color:${h.color}">${h.stage}</span>
        <span class="op-tl-score" style="color:${h.color}">${h.score}</span>
      </div>`).join('');
  }

  // AI summary sentence
  const aiEl = $('wsAIText');
  if (aiEl) {
    const exec_sum = (ii && ii.executive_summary) || (d.story && d.story.executive_summary) || '';
    aiEl.textContent = exec_sum ? exec_sum.split('.')[0] + '.' : 'Loading institutional read...';
  }

  // ── Zone 4: Pressure Panel ────────────────────────────────────────────────
  const pressEl = $('wsPressurePanel');
  if (pressEl) {
    const m1 = (eie && eie.pressure_acceleration) || {};
    const m3 = (eie && eie.absorption) || {};
    const m4 = (eie && eie.exhaustion) || {};
    const m5 = (eie && eie.delta_acceleration) || {};
    const fi2 = d.flow_intelligence_2 || {};
    const swScore   = Number(fi2.sweep_pressure || 50);
    const blkScore  = Number(fi2.block_conviction || 50);
    const absScore  = Number(m3.score || 50);
    const pAccel    = m1.direction || 'STABLE';
    const dAccel    = m5.direction || 'STABLE';
    const exhaust   = m4.state || 'BALANCED';

    const arrow = dir => dir.includes('ACCELER') ? '↑↑' : dir.includes('DECEL') ? '↓' : dir === 'STABLE' ? '→' : '';
    const arrowColor = dir => dir.includes('BULL') || dir === 'STABLE' ? 'var(--green)' : dir.includes('BEAR') ? 'var(--red)' : 'var(--faint)';
    const bc = s => s >= 70 ? 'var(--green)' : s >= 45 ? 'var(--blue)' : 'var(--red)';

    const _prow = (label, value, score, arrDir) => `
      <div class="ws-pr-row">
        <span class="ws-pr-label">${label}</span>
        <span class="ws-pr-val" style="color:${bc(score)}">${esc(value)}</span>
        <span class="ws-pr-arrow" style="color:${arrowColor(arrDir || '')}">${arrow(arrDir || '')}</span>
        <div class="ws-pr-bar"><div style="width:${Math.min(score,100)}%;background:${bc(score)}"></div></div>
      </div>`;

    const premVel   = m1.avg_delta_m ? (m1.avg_delta_m > 0 ? 'Accelerating Calls' : 'Accelerating Puts') : 'Stable';
    const deltaVel  = m5.direction ? m5.direction.replace(/_/g,' ').replace('ACCELERATING ','').replace('DECELERATING ','Slowing ') : 'Stable';
    const exhLabel  = exhaust.includes('BUYER') ? 'Buyers Exhausted' : exhaust.includes('SELLER') ? 'Sellers Exhausted' : exhaust === 'BALANCED' ? 'Balanced' : 'Aggressive ' + exhaust.split('_')[0];

    pressEl.innerHTML = `
      ${_prow('Premium Velocity', premVel,   swScore,  pAccel)}
      ${_prow('Delta Velocity',   deltaVel,  Number(m5.score || 50), dAccel)}
      ${_prow('Sweep Pressure',   swScore >= 70 ? 'High Urgency' : swScore >= 45 ? 'Moderate' : 'Low',  swScore, pAccel)}
      ${_prow('Block Conviction', blkScore >= 70 ? 'High Conviction' : 'Moderate',                       blkScore, '')}
      ${_prow('Liquidity Abs.',   absScore >= 70 ? 'Absorbing' : 'Normal',                               absScore, '')}
      ${_prow('Aggression',       exhLabel,  exhaust === 'BALANCED' ? 55 : 70, '')}
    `;
  }

  // Why bullets (shared with DCC)
  const whyEl    = $('wsWhyBullets');
  const whyLbl   = $('wsWhyLabel');
  if (whyEl && eie && eie.why_bullets) {
    const isEnter = decision.startsWith('ENTER');
    if (whyLbl) { whyLbl.textContent = isEnter ? 'Enter Because' : 'Blocked By'; whyLbl.style.color = isEnter ? 'var(--green)' : 'var(--red)'; }
    whyEl.innerHTML = (eie.why_bullets || []).slice(0, 5).map(b => `
      <div class="op-why-row">
        <span class="op-why-dot ${b.ok ? 'eie-ok' : 'eie-no'}">${b.ok ? '✓' : '✗'}</span>
        <span class="op-why-text ${b.ok ? 'eie-ok' : 'eie-no'}">${esc(b.label || b.text || '')}</span>
      </div>`).join('');
  }

  // ── Zone 5: Trade Card ────────────────────────────────────────────────────
  const cardEl    = $('wsTradeCard');
  const waitingEl = $('wsTradeWaiting');
  const threshold = 75;
  const showCard  = execScore >= threshold && decision !== 'NO_TRADE' && decision !== 'PREPARING';

  if (cardEl && waitingEl) {
    cardEl.style.display    = showCard ? '' : 'none';
    waitingEl.style.display = showCard ? 'none' : '';
  }

  if (showCard && tc) {
    const isCall   = decision.includes('CALL');
    const cardColor = isCall ? 'var(--green)' : 'var(--red)';
    const setTC = (id, val, col) => { const e = $(id); if (e) { e.textContent = val || '--'; if (col) e.style.color = col; } };
    setTC('wsTradeDir',   isCall ? '▲ CALL' : '▼ PUT', cardColor);
    setTC('wsTradeProb',  eie ? Math.round(eie.exec_probability) + '% probability' : '');
    setTC('wsTradeEntry', tc.entry_zone || '--');
    setTC('wsTradeStop',  tc.stop ? '$' + fmt(Number(tc.stop)) : '--');
    setTC('wsTradeT1',    tc.target1 ? '$' + fmt(Number(tc.target1)) : '--');
    setTC('wsTradeT2',    tc.target2 ? '$' + fmt(Number(tc.target2)) : '--');
    setTC('wsTradeRisk',  '--');
    setTC('wsTradeReward','--');
    setTC('wsTradeDuration', tc.expected_holding_time || '5–15 min');
    setTC('wsTradeContract', tc.contract_hint || '');
    setTC('wsTradeInvalidation', eie ? eie.invalidation || '' : '');
    if (cardEl) cardEl.style.borderColor = cardColor + '40';
  }

  // Waiting state mini-ring
  const twRingFill = $('wsTWRingFill');
  const twScore    = $('wsTWScore');
  const twStage    = $('wsTWStage');
  const twDesc     = $('wsTWDesc');
  if (!showCard) {
    if (twRingFill) {
      twRingFill.style.strokeDashoffset = (150.8 * (1 - execScore / 100)).toString();
      twRingFill.style.stroke = stageColor;
    }
    if (twScore) { twScore.textContent = Math.round(execScore); twScore.style.color = stageColor; }
    if (twStage) { twStage.textContent = stage; twStage.style.color = stageColor; }
    if (twDesc)  { twDesc.textContent  = eie ? (eie.stage_description || 'Monitoring') : 'Monitoring'; }
  }
}

// Wire renderWorkspace into the load cycle

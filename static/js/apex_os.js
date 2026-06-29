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
  const dec = d.decision_state || '';
  const str = d.structure || {};

  const decCls  = dec.includes('CALL') ? 'rv-green' : dec.includes('PUT') ? 'rv-red' : dec.includes('WATCH') || dec === 'READY' ? 'rv-amber' : 'rv-muted';
  const cellCls = dec.includes('CALL') ? 'rdc-call' : dec.includes('PUT') ? 'rdc-put' : dec.includes('WATCH') || dec === 'READY' ? 'rdc-watch' : 'rdc-no';
  const poc     = ms.poc || str.session_poc;
  const vwap    = ms.vwap || r.vwap || str.vwap;
  const pocMig  = ms.poc_migration || '';
  const confLevel = ms.confluence_level;
  const tapeBias  = ms.tape_bias || '';
  const net_flow  = r.net_flow || 0;

  el.innerHTML = `
    <div class="ribbon-cell">
      <div class="ribbon-label">SPX Price</div>
      <div class="ribbon-val rv-blue">$${fmt(r.spx_price || fl.stock_price || ms.price)}</div>
      <div class="ribbon-sub">${activeTicker}</div>
    </div>
    <div class="ribbon-cell">
      <div class="ribbon-label">Basis</div>
      <div class="ribbon-val rv-muted">$${fmt(r.es_price || ms.es_price || r.spx_price)}</div>
      <div class="ribbon-sub">ES Futures</div>
    </div>
    <div class="ribbon-cell">
      <div class="ribbon-label">Call Wall</div>
      <div class="ribbon-val rv-green">$${fmt(r.call_wall || g.call_wall || ms.call_wall)}</div>
      <div class="ribbon-sub">GEX: ${fmtI(r.gex_score || ms.gex_score)}</div>
    </div>
    <div class="ribbon-cell">
      <div class="ribbon-label">Gamma Flip</div>
      <div class="ribbon-val rv-amber">$${fmt(r.zero_gamma || g.zero_gamma || ms.zero_gamma)}</div>
      <div class="ribbon-sub">${(g.regime_display || '').split(' ').slice(0,2).join(' ') || '--'}</div>
    </div>
    <div class="ribbon-cell">
      <div class="ribbon-label">Put Wall</div>
      <div class="ribbon-val rv-red">$${fmt(r.put_wall || g.put_wall || ms.put_wall)}</div>
      <div class="ribbon-sub">GEX shield</div>
    </div>
    <div class="ribbon-cell">
      <div class="ribbon-label">VWAP / POC</div>
      <div class="ribbon-val rv-blue">$${fmt(vwap)}</div>
      <div class="ribbon-sub">POC: $${poc ? fmt(poc) : '--'}${pocMig ? ' · ' + pocMig.toLowerCase().replace('_',' ') : ''}</div>
    </div>
    <div class="ribbon-cell">
      <div class="ribbon-label">Net Flow</div>
      <div class="ribbon-val ${net_flow >= 0 ? 'rv-green' : 'rv-red'}">$${fmtM(net_flow)}</div>
      <div class="ribbon-sub">Tape: ${tapeBias || r.flow_momentum || '--'}</div>
    </div>
    <div class="ribbon-cell">
      <div class="ribbon-label">Inst. Confidence</div>
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
  const ici   = d.ici || {};
  const score = Number(ici.ici || 0);
  const color = ici.ici_color === 'GREEN' ? 'ici-green' : ici.ici_color === 'RED' ? 'ici-red' : 'ici-amber';
  const comps = ici.components || {};
  const wts   = ici.weights || {};

  const compHTML = [
    { key: 'conviction',      label: 'Consensus', w: wts.conviction || 0.5 },
    { key: 'freshness',       label: 'Signal Freshness', w: wts.freshness || 0.2 },
    { key: 'gamma_stability', label: 'Gamma Stability', w: wts.gamma || 0.15 },
    { key: 'flow_momentum',   label: 'Flow Momentum', w: wts.momentum || 0.15 },
  ].map(c => {
    const val = Number(comps[c.key] || 0);
    const barColor = val >= 70 ? 'var(--green)' : val >= 45 ? 'var(--blue)' : 'var(--red)';
    return `<div class="ici-comp">
      <div class="ici-comp-label">${c.label} <span class="ici-weight">${(c.w * 100).toFixed(0)}%</span></div>
      <div class="ici-comp-bar"><div class="ici-comp-fill" style="width:${val}%;background:${barColor}"></div></div>
      <div class="ici-comp-val">${val.toFixed(1)}</div>
    </div>`;
  }).join('');

  el.innerHTML = `
    <div class="ici-row">
      <div class="ici-big ${color}">${fmtI(score)}</div>
      <div class="ici-meta">
        <div class="ici-label" style="color:${ici.ici_color === 'GREEN' ? 'var(--green)' : ici.ici_color === 'RED' ? 'var(--red)' : 'var(--amber)'}">${ici.ici_label || '--'} CONFIDENCE</div>
        <div class="ici-status">${esc(ici.ici_status || '--')}</div>
        <div class="ici-components">${compHTML}</div>
      </div>
      <div class="ici-grade" style="color:${score >= 85 ? 'var(--green)' : score >= 70 ? 'var(--blue)' : score >= 55 ? 'var(--amber)' : 'var(--red)'}">${d.grade || '--'}</div>
    </div>
  `;
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
    const readEl = $('readinessNum');
    if (readEl) {
      const pctR = gates.length ? Math.round(passCount / gates.length * 100) : 0;
      readEl.textContent = pctR;
      readEl.className = 'ici-big ' + (pctR >= 75 ? 'ici-green' : pctR >= 50 ? 'ici-amber' : 'ici-red');
    }
    gcEl.innerHTML = gates.map(g =>
      `<div class="gate-row"><span class="gate-dot ${g.ok ? 'gd-on' : 'gd-off'}"></span>${esc(g.label)}</div>`
    ).join('');
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
    const sessState = (d.ici || {}).session_state || 'CLOSED';
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
    const s = sess.session || '';
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
  const ici = Number((d.ici || {}).ici || d.confidence || 0);
  const state = d.decision_state || (d.decision || {}).state || 'NO_TRADE';
  const session = (d.session || {}).session || '--';
  const flow = d.flow || d.flow_intelligence || {};
  const gamma = d.gamma_regime || {};
  const price = (d.ribbon || {}).spx_price || flow.stock_price;
  const cls = state.includes('CALL') ? 'cmd-call' : state.includes('PUT') ? 'cmd-put' : state.includes('READY') || state.includes('WATCH') ? 'cmd-watch' : 'cmd-no';
  const flowTxt = `${fmtI(flow.flow_score)} / ${fmtI(flow.order_flow_score)}`;
  const netFlow = flow.net_premium != null ? '$' + fmtM(flow.net_premium) : '$' + fmtM((d.ribbon || {}).net_flow);
  el.innerHTML = `
    <div class="cmd-decision ${cls}">${esc(state.replace(/_/g, ' '))}</div>
    <div class="cmd-row"><span>ICI</span><b>${fmtI(ici)}%</b></div>
    <div class="cmd-row"><span>SPX</span><b>$${fmt(price)}</b></div>
    <div class="cmd-row"><span>Session</span><b>${esc(session)}</b></div>
    <div class="cmd-row"><span>Flow / Order</span><b>${flowTxt}</b></div>
    <div class="cmd-row"><span>Net Flow</span><b>${netFlow}</b></div>
    <div class="cmd-row"><span>Gamma</span><b>${esc(gamma.regime_display || gamma.regime_label || '--')}</b></div>
    <div class="cmd-row"><span>Call / Put Wall</span><b>${fmt(gamma.call_wall || (d.ribbon || {}).call_wall)} / ${fmt(gamma.put_wall || (d.ribbon || {}).put_wall)}</b></div>
  `;
}


function renderAuctionPanel(d) {
  const el = $('auctionPanel');
  if (!el || !d) return;
  const vp = d.volume_profile || {};
  const levels = vp.levels || {};
  const auction = d.auction || {};
  const flags = auction.quality_flags || vp.quality_flags || [];
  const mig = auction.poc_migration || '--';
  const migCls = mig === 'RISING' ? 'rv-green' : mig === 'FALLING' ? 'rv-red' : 'rv-amber';
  el.innerHTML = `
    <div class="cmd-row"><span>POC</span><b>$${fmt(levels.poc || auction.poc)}</b></div>
    <div class="cmd-row"><span>VAH / VAL</span><b>$${fmt(levels.vah || auction.vah)} / $${fmt(levels.val || auction.val)}</b></div>
    <div class="cmd-row"><span>POC Migration</span><b class="${migCls}">${esc(mig)}</b></div>
    <div class="cmd-row"><span>Auction State</span><b>${esc((auction.auction_state || '--').replace(/_/g,' '))}</b></div>
    <div class="auction-note">${esc(auction.narrative || vp.message || 'Waiting for profile data.')}</div>
    ${flags.length ? `<div class="mini-blockers">${flags.slice(0,3).map(x => `<div>• ${esc(String(x).replace(/_/g,' '))}</div>`).join('')}</div>` : ''}
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
function renderStory(d) {
  const el = $('storyPanel');
  if (!el || !d) return;
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

  const chapters = story.chapters || [];
  if (!chapters.length) {
    el.innerHTML = '<div style="color:var(--faint);font-size:12px;padding:12px">No story chapters available yet.</div>';
    const narr = $('narrativeBlock');
    if (narr && story.full_narrative) narr.textContent = story.full_narrative;
    return;
  }

  el.innerHTML = '<div class="story-timeline">' + chapters.map((c, i) => `
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
    </div>`).join('') + '</div>';

  const narr = $('narrativeBlock');
  if (narr && story.full_narrative) narr.textContent = story.full_narrative;
}

/* ── Replay ───────────────────────────────────────────────────────────────── */
function captureReplaySnap(d) {
  if (!d) return;
  const snap = {
    ts:      new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true, timeZone: 'America/New_York' }),
    state:   d.decision_state || '--',
    ici:     Number((d.ici || {}).ici || 0),
    price:   (d.ribbon || {}).spx_price || ((d.flow_intelligence || d.flow || {}).stock_price) || null,
    exec:    (d.execution || {}).execution_state || '--',
    flow:    (d.flow_intelligence || {}).flow_momentum || '--',
    notes:   ((d.flow_intelligence || {}).notes || []).slice(0, 2),
    summary: d.executive_summary || '',
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
  if (!['ENTER_CALL','ENTER_PUT','READY'].includes(state)) return; // only log actionable states
  reviewLog.unshift({
    ts:      new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true, timeZone: 'America/New_York' }),
    ticker:  activeTicker,
    state,
    ici:     Number((d.ici || {}).ici || 0),
    summary: d.executive_summary || '',
    coach:   (d.trade_coach || {}).action || '',
    contract:(d.trade_coach || d.risk || {}).contract_hint || '',
  });
  if (reviewLog.length > 40) reviewLog.pop();
  renderReview();
}

function renderReview() {
  const el = $('reviewPanel');
  if (!el) return;
  if (!reviewLog.length) {
    el.innerHTML = '<div class="review-empty">No actionable signals logged yet this session.<br>ENTER_CALL, ENTER_PUT, and READY states are captured automatically.</div>';
    return;
  }
  el.innerHTML = reviewLog.map(r => {
    const cls = r.state.includes('CALL') ? 'var(--green)' : r.state.includes('PUT') ? 'var(--red)' : 'var(--amber)';
    return `<div class="review-card">
      <div class="rc-header">
        <div class="rc-ticker" style="color:${cls}">${r.ticker} — ${r.state.replace(/_/g,' ')}</div>
        <div class="rc-time">${r.ts} · ICI ${fmtI(r.ici)}</div>
      </div>
      ${r.contract ? `<div style="font-family:var(--mono);font-size:12px;color:var(--blue);margin-bottom:4px">${esc(r.contract)}</div>` : ''}
      ${r.coach    ? `<div class="rc-result">${esc(r.coach)}</div>` : ''}
      ${r.summary  ? `<div class="rc-result" style="margin-top:4px;font-size:10px;color:var(--faint)">${esc(r.summary)}</div>` : ''}
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
  ['runScanBtn', 'runScanBtnPanel'].forEach(id => {
    const b = $(id);
    if (b) {
      b.disabled = !!disabled;
      b.classList.toggle('is-loading', !!disabled);
      b.textContent = disabled ? 'Scanning...' : '▶ Run Scan';
    }
  });
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
  ['runScanBtn', 'runScanBtnPanel'].forEach(id => {
    const b = $(id);
    if (b) b.addEventListener('click', runManualScan);
  });
  const refreshScanner = $('refreshScannerBtn');
  if (refreshScanner) refreshScanner.addEventListener('click', loadScannerIdeas);
  const resetTimeline = $('resetTimelineBtn');
  if (resetTimeline) resetTimeline.addEventListener('click', resetConfidenceTimeline);
}

/* ════════════════════════════════════════════════════════════════════════════
   MASTER LOAD
   ════════════════════════════════════════════════════════════════════════════ */

async function fetchInstitutionalOS() {
  const primaryUrl = '/api/institutional_os?ticker=' + encodeURIComponent(activeTicker) + '&heatmap=1';
  const fallbackUrl = '/api/institutional_os?ticker=' + encodeURIComponent(activeTicker) + '&heatmap=0';
  try {
    const r = await fetch(primaryUrl, { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    if (!data.ok) throw new Error(data.error || 'API error');
    return { data, fallbackUsed: false, primaryError: null };
  } catch (primaryErr) {
    const r2 = await fetch(fallbackUrl, { cache: 'no-store' });
    if (!r2.ok) throw new Error('Primary failed (' + primaryErr.message + '); fallback failed HTTP ' + r2.status);
    const data2 = await r2.json();
    if (!data2.ok) throw new Error('Primary failed (' + primaryErr.message + '); fallback failed: ' + (data2.error || 'API error'));
    return { data: data2, fallbackUsed: true, primaryError: primaryErr.message };
  }
}

async function loadOS() {
  const errEl = $('osError');
  try {
    const apiResult = await fetchInstitutionalOS();
    const data = apiResult.data;
    osData = data;
    if (errEl) {
      if (apiResult.fallbackUsed) {
        errEl.style.display = '';
        errEl.textContent = 'Heatmap mode failed; dashboard loaded without heatmap. ' + (apiResult.primaryError || '');
      } else {
        errEl.style.display = 'none';
        errEl.textContent = '';
      }
    }

    // 6.0.3 panels
    renderRibbon(data);
    renderICI(data);
    renderDecision(data);
    renderTradeCoach(data);
    renderEngineMatrix(data);
    renderSession(data);
    renderHeatmap(data);
    recordConfidencePoint(data);
    renderCommandCenter(data);
    renderAuctionPanel(data);
    renderCoachSnapshot(data);
    await loadConfidenceTimeline();

    // 6.0.4 panels
    renderFlow2(data);
    renderStory(data);
    renderOvernightGamePlan(data);

    // Render market status banner from data if present
    if (data.market_status) renderMarketStatusBanner(data.market_status);

    // Replay + Review capture
    captureReplaySnap(data);
    addReviewEntry(data);

    // 6.3.2 — refresh flow tape on each OS load
    loadFlowTape();

    const lu = $('lastUpdated');
    if (lu) lu.textContent = 'Updated: ' + (data.updated_at_et || new Date().toLocaleTimeString());
  } catch (e) {
    if (errEl) { errEl.style.display = ''; errEl.textContent = 'Institutional OS data error: ' + e.message; } console.error('APEX OS load failed', e);
  }
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

function renderFlowTapeTable() {
  const el = $('flowTapeTable');
  if (!el) return;
  const rows = filteredTapeRows();
  if (!rows.length) {
    el.innerHTML = '<div class="tape-empty">No flow tape rows match the current filter.</div>';
    return;
  }
  const rowHtml = rows.slice(0, 80).map(r => {
    const agCls = r.aggressor_side === 'BUY' ? 'tape-row-buy' : r.aggressor_side === 'SELL' ? 'tape-row-sell' : 'tape-row-neutral';
    const label = esc(r.tape_label || '--').replace('_', ' ');
    const imp   = r.importance_score != null ? `<span class="tape-importance">${r.importance_score}</span>` : '';
    return `<tr class="${agCls}">
      <td>${esc(r.time_et||'')}</td>
      <td><b>${esc(r.ticker)}</b></td>
      <td>${esc(r.contract_type||'')}</td>
      <td>${r.strike ? fmt(r.strike) : '--'}</td>
      <td>${esc(r.expiration||'')}</td>
      <td><b>${fmtPremium(r.premium)}</b></td>
      <td><span class="tape-label">${label}</span>${imp}</td>
    </tr>`;
  }).join('');
  el.innerHTML = `<table>
    <thead><tr>
      <th>Time</th><th>Ticker</th><th>Type</th><th>Strike</th>
      <th>Exp</th><th>Premium</th><th>Label / Score</th>
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
  initReplayControls();
  initTickerSelect();
  initRefreshBtn();
  initRunScanButtons();
  initTapeFilters();
  initOverlayToggles();
  initReviewForm();
  initReplayDatePicker();

  // Activate first tab
  document.querySelector('.tab-btn[data-tab="dashboard"]')?.click();

  loadOS();
  loadScannerIdeas();
  loadFlowTape();
  loadReviewSummary();
  loadTradeHistory();
  loadMarketStatus();

  setInterval(loadOS, AUTO_INTERVAL);
  setInterval(loadScannerIdeas, 30000);
  setInterval(loadFlowTape, 45000);
  setInterval(loadMarketStatus, 60000);  // Status banner refreshes every minute
});

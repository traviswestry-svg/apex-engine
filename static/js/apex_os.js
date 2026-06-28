/**
 * APEX Institutional OS — Sprint 6.0.3 / 6.0.4
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
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.tab;
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === target));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.toggle('active', p.id === 'tab-' + target));
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
  const g   = (d.gamma_regime || {});
  const dec = d.decision_state || '';

  const decCls = dec.includes('CALL') ? 'rv-green' : dec.includes('PUT') ? 'rv-red' : 'rv-amber';

  el.innerHTML = `
    <div class="ribbon-cell">
      <div class="ribbon-label">SPX Price</div>
      <div class="ribbon-val rv-blue">$${fmt(r.spx_price || fl.stock_price || g.stock_price)}</div>
      <div class="ribbon-sub">${activeTicker}</div>
    </div>
    <div class="ribbon-cell">
      <div class="ribbon-label">Inst. Confidence</div>
      <div class="ribbon-val ${ici.ici_color === 'GREEN' ? 'rv-green' : ici.ici_color === 'RED' ? 'rv-red' : 'rv-amber'}">${fmtI(ici.ici)}</div>
      <div class="ribbon-sub">${ici.ici_label || '--'} · ${d.grade || '--'}</div>
    </div>
    <div class="ribbon-cell">
      <div class="ribbon-label">Decision</div>
      <div class="ribbon-val ${decCls}" style="font-size:12px;margin-top:5px">${(dec || 'LOADING').replace(/_/g, ' ')}</div>
      <div class="ribbon-sub">${d.readiness ? d.readiness.replace(/_/g,' ') : '--'}</div>
    </div>
    <div class="ribbon-cell">
      <div class="ribbon-label">Net Flow</div>
      <div class="ribbon-val ${(r.net_flow || 0) >= 0 ? 'rv-green' : 'rv-red'}">$${fmtM(r.net_flow)}</div>
      <div class="ribbon-sub">${r.flow_momentum ? r.flow_momentum.replace(/_/g,' ') : '--'}</div>
    </div>
    <div class="ribbon-cell">
      <div class="ribbon-label">Call Wall</div>
      <div class="ribbon-val rv-green">$${fmt(r.call_wall || g.call_wall)}</div>
      <div class="ribbon-sub">Put: $${fmt(r.put_wall || g.put_wall)}</div>
    </div>
    <div class="ribbon-cell">
      <div class="ribbon-label">Zero Gamma</div>
      <div class="ribbon-val rv-amber">$${fmt(r.zero_gamma || g.zero_gamma)}</div>
      <div class="ribbon-sub">${g.regime_display || g.regime_label || '--'}</div>
    </div>
    <div class="ribbon-cell">
      <div class="ribbon-label">VWAP</div>
      <div class="ribbon-val rv-muted">$${fmt(r.vwap || (d.structure || {}).vwap)}</div>
      <div class="ribbon-sub">POC: $${fmt(r.poc || (d.structure || {}).session_poc)}</div>
    </div>
    <div class="ribbon-cell">
      <div class="ribbon-label">Updated</div>
      <div class="ribbon-val rv-muted" style="font-size:12px;margin-top:5px">${r.updated_at_et || d.updated_at_et || '--'}</div>
      <div class="ribbon-sub">Auto 12s</div>
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
  const nBull = cons.n_bullish  || 0;
  const nBear = cons.n_bearish  || 0;
  const nNeut = cons.n_neutral  || 0;
  const nTot  = cons.n_engines  || 6;
  const consEl = $('consensusBar');
  if (consEl) {
    consEl.innerHTML = `
      <div class="consensus-bars">
        <div class="cb-bull" style="flex:${nBull}"></div>
        <div class="cb-neut" style="flex:${nNeut}"></div>
        <div class="cb-bear" style="flex:${nBear}"></div>
      </div>
      <div class="consensus-meta">
        <span style="color:var(--green)">▲ ${nBull} Bull</span>
        <span>${cons.consensus_label || '--'}</span>
        <span style="color:var(--red)">▼ ${nBear} Bear</span>
      </div>
    `;
  }

  if (!contribs.length) {
    el.innerHTML = '<div style="color:var(--faint);font-size:12px;padding:10px">No engine data yet.</div>';
    return;
  }

  el.innerHTML = contribs.map((e, idx) => {
    const score = Number(e.score || 0);
    const vote  = (e.vote || 'NEUTRAL').toUpperCase();
    const voteCls = vote === 'BULLISH' ? 'ev-bull' : vote === 'BEARISH' ? 'ev-bear' : 'ev-neut';
    const voteLabel = vote === 'BULLISH' ? '▲ BULL' : vote === 'BEARISH' ? '▼ BEAR' : '— NEUT';
    const barColor = score >= 65 ? 'var(--green)' : score >= 40 ? 'var(--blue)' : 'var(--red)';
    const notes = (e.notes || []).slice(0, 3);
    const notesHTML = notes.length
      ? '<div class="em-notes" id="em-notes-' + idx + '">' + notes.map(n => `<div class="em-note-item">· ${esc(n)}</div>`).join('') + '</div>'
      : '';
    return `
      <div class="em-row" id="em-row-${idx}" onclick="toggleEmRow(${idx},${notes.length > 0})" style="cursor:${notes.length > 0 ? 'pointer' : 'default'}">
        <div class="em-name">${esc(e.label || e.engine)}</div>
        <div class="em-vote ${voteCls}">${voteLabel}</div>
        <div class="em-bar-wrap"><div class="em-bar" style="width:${score}%;background:${barColor}"></div></div>
        <div class="em-score">${score > 0 ? score.toFixed(0) : '--'}</div>
      </div>
      ${notesHTML}
    `;
  }).join('');
}

function toggleEmRow(idx, hasNotes) {
  if (!hasNotes) return;
  const row   = $('em-row-' + idx);
  const notes = $('em-notes-' + idx);
  if (!row || !notes) return;
  row.classList.toggle('expanded');
  notes.style.display = row.classList.contains('expanded') ? 'flex' : 'none';
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
  const timeline = d.story_timeline || [];

  // Executive summary
  const summEl = $('execSummary');
  if (summEl) summEl.textContent = d.executive_summary || story.executive_summary || '--';

  const chapters = story.chapters || [];
  if (!chapters.length && !timeline.length) {
    el.innerHTML = '<div style="color:var(--faint);font-size:12px;padding:12px">No story chapters yet.</div>';
    return;
  }

  // Use chapters (richer) over story_timeline
  const src = chapters.length ? chapters : timeline.map(t => ({ chapter: t.title, text: t.text, time: '--', color: 'var(--muted)', significance: t.step }));

  el.innerHTML = '<div class="story-timeline">' + src.map((c, i) => `
    <div class="story-entry">
      <div class="story-connector">
        <div class="s-dot" style="background:${esc(c.color || 'var(--faint)')}"></div>
        ${i < src.length - 1 ? '<div class="s-line"></div>' : ''}
      </div>
      <div class="story-body">
        <div class="story-chapter" style="color:${esc(c.color || 'var(--muted)')}">${esc(c.chapter || c.title || 'Chapter')}</div>
        <div class="story-text">${esc(c.text || c.narrative || '')}</div>
        <div class="story-time">${esc(c.time || '--')}</div>
      </div>
    </div>`).join('') + '</div>';

  // Full narrative
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
  el.innerHTML = summary + `<div class="scanner-grid">` + ideas.slice(0, 24).map(idea => {
    const side = (idea.direction || idea.side || idea.approved_side || '').toUpperCase();
    const isPut = side.includes('PUT');
    const isCall = side.includes('CALL');
    const cls = isCall ? 'scanner-call' : isPut ? 'scanner-put' : '';
    const ticker = idea.ticker || '--';
    const grade = idea.grade || idea.alert_tier || '--';
    const score = idea.final_score ?? idea.conviction_score ?? idea.score ?? idea.breakout_probability;
    const price = idea.price ?? idea.stock_price ?? idea.spot_price;
    const statusText = idea.status || idea.trade_permission || idea.breakout_probability_label || '';
    const contract = idea.option_contract || idea.recommended_contract || idea.contract_hint || '';
    const notes = Array.isArray(idea.notes) ? idea.notes.slice(0, 3).join(' · ') : (idea.no_trade_reason || idea.strategy || '');
    return `<div class="scanner-idea ${cls}">
      <div class="scanner-idea-top">
        <div><span class="scanner-ticker">${esc(ticker)}</span><span class="scanner-side">${esc(side || 'WATCH')}</span></div>
        <div class="scanner-grade">${esc(grade)}</div>
      </div>
      <div class="scanner-meta">
        <span>Score ${score != null ? esc(Number(score).toFixed(1)) : '--'}</span>
        <span>Price ${price != null ? '$' + fmt(price) : '--'}</span>
        ${statusText ? `<span>${esc(statusText)}</span>` : ''}
      </div>
      ${contract ? `<div class="scanner-contract">${esc(contract)}</div>` : ''}
      ${notes ? `<div class="scanner-notes">${esc(notes)}</div>` : ''}
    </div>`;
  }).join('') + `</div>`;
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
}

/* ════════════════════════════════════════════════════════════════════════════
   MASTER LOAD
   ════════════════════════════════════════════════════════════════════════════ */

async function loadOS() {
  const errEl = $('osError');
  try {
    const r = await fetch('/api/institutional_os?ticker=' + activeTicker + '&heatmap=1', { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    if (!data.ok) throw new Error(data.error || 'API error');
    osData = data;
    if (errEl) errEl.style.display = 'none';

    // 6.0.3 panels
    renderRibbon(data);
    renderICI(data);
    renderDecision(data);
    renderTradeCoach(data);
    renderEngineMatrix(data);
    renderSession(data);
    renderHeatmap(data);

    // 6.0.4 panels
    renderFlow2(data);
    renderStory(data);

    // Replay + Review capture
    captureReplaySnap(data);
    addReviewEntry(data);

    const lu = $('lastUpdated');
    if (lu) lu.textContent = 'Updated: ' + (data.updated_at_et || new Date().toLocaleTimeString());
  } catch (e) {
    if (errEl) { errEl.style.display = ''; errEl.textContent = 'Error: ' + e.message; }
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

/* ── Init ─────────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  initReplayControls();
  initTickerSelect();
  initRefreshBtn();
  initRunScanButtons();

  // Activate first tab
  document.querySelectorAll('.tab-btn')[0]?.click();

  loadOS();
  loadScannerIdeas();
  setInterval(loadOS, AUTO_INTERVAL);
  setInterval(loadScannerIdeas, 30000);
});

(() => {
  const $ = id => document.getElementById(id);
  let ticker = 'SPX';
  let timeframe = 5;
  let refreshTimer = null;
  const escapeHtml = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = (v,d=2) => (v===null||v===undefined||v===''||Number.isNaN(Number(v))) ? '—' : Number(v).toLocaleString(undefined,{maximumFractionDigits:d});
  const money = v => (v===null||v===undefined||Number.isNaN(Number(v))) ? '—' : '$'+Number(v).toLocaleString(undefined,{maximumFractionDigits:2});
  const cls = v => { const s=String(v||'').toUpperCase(); return /BULL|BUY|CALL|READY|LIVE|OPEN|POSITIVE|PASS|HEALTH/.test(s)?'green':/BEAR|SELL|PUT|CLOSED|FAIL|ERROR|BLOCK/.test(s)?'red':/WAIT|PREPAR|MIXED|NEUTRAL|LOW|WATCH|PARTIAL/.test(s)?'amber':'blue'; };
  const metric = (k,v,s='') => `<div class="metric"><div class="k">${escapeHtml(k)}</div><div class="v ${cls(v)}">${escapeHtml(v ?? '—')}</div>${s?`<div class="s">${escapeHtml(s)}</div>`:''}</div>`;
  const errorBox = msg => `<div class="error-state">${escapeHtml(msg||'Unavailable')}</div>`;
  const emptyBox = msg => `<div class="empty-state">${escapeHtml(msg||'No data')}</div>`;
  async function get(url){ const r=await fetch(url,{cache:'no-store'}); let j={}; try{j=await r.json()}catch(e){} if(!r.ok) throw new Error(j.error||j.reason||`HTTP ${r.status}`); return j; }
  function setRefresh(ok,msg){ $('liveDot').classList.toggle('bad',!ok); $('refreshState').textContent=msg; }
  function updateClock(){ $('topClock').textContent=new Date().toLocaleTimeString('en-US',{timeZone:'America/New_York',hour:'numeric',minute:'2-digit',second:'2-digit'})+' ET'; }

  async function loadMission(){
    const el=$('missionContent');
    try{
      const d=await get(`/api/mission_control?ticker=${encodeURIComponent(ticker)}`), q=d.decision||{}, tc=d.trade_card||{}, f=d.flow||{}, dealer=d.dealer||{};
      $('statusSession').textContent=d.session_state||'—'; $('statusPrice').textContent=money(d.price); $('statusDecision').textContent=q.decision_state||q.stage||'—'; $('statusIci').textContent=q.institutional_confidence??'—'; $('statusFlow').textContent=f.bias||'—'; $('statusUpdated').textContent=d.updated_at_et||'—';
      el.innerHTML=`<div class="metric-grid">${metric('Institutional Bias',q.institutional_bias)}${metric('Decision',q.decision_state,q.recommendation||'')}${metric('Stage',q.stage,q.stage_description||'')}${metric('ICI',q.institutional_confidence,q.confidence_label||'')}${metric('Flow',f.bias,'Urgency: '+(f.urgency||'—'))}${metric('Gamma',dealer.gamma_regime,'Dealer: '+(dealer.bias||'—'))}</div><div class="narrative" style="margin-top:9px">${escapeHtml(q.narrative||'No institutional narrative available.')}</div>${(d.why_bullets||[]).length?`<ul class="bullet-list">${d.why_bullets.slice(0,5).map(x=>`<li>${escapeHtml(x)}</li>`).join('')}</ul>`:''}${tc.active?`<div class="metric-grid" style="margin-top:9px">${metric('Trade',tc.direction,tc.contract_hint||'')}${metric('Entry',Array.isArray(tc.entry_zone)?tc.entry_zone.join(' – '):tc.entry_zone)}${metric('Stop',tc.stop)}${metric('Target 1',tc.target1)}${metric('Target 2',tc.target2)}${metric('Probability',tc.probability)}</div>`:''}`;
    }catch(e){el.innerHTML=errorBox(e.message)}
  }

  async function loadExecution(){
    const el=$('executionContent');
    try{
      const [r,p]=await Promise.allSettled([get('/api/execution/readiness'),get('/api/execution/plan')]);
      const d=r.status==='fulfilled'?r.value:{}, plan=p.status==='fulfilled'?p.value:{};
      const x=d.execution||d, checks=d.checks||x.checks||[];
      el.innerHTML=`<div class="metric-grid">${metric('Ready',x.ready??d.ready??d.status)}${metric('Score',x.score??x.execution_score??d.score)}${metric('Quality',x.quality??x.execution_quality??'—')}${metric('Liquidity',x.liquidity??x.liquidity_state??'—')}${metric('Fill Probability',x.fill_probability??'—')}${metric('Plan',plan.state||plan.status||plan.action||'—')}</div>${Array.isArray(checks)&&checks.length?`<ul class="bullet-list">${checks.slice(0,6).map(c=>`<li>${escapeHtml(c.name||c.check||'Check')}: <b class="${cls(c.status||c.ok)}">${escapeHtml(c.status??c.ok)}</b></li>`).join('')}</ul>`:''}`;
    }catch(e){el.innerHTML=errorBox(e.message)}
  }

  async function loadAnalysis(){
    const el=$('analysisContent');
    try{
      const d=await get(`/api/institutional-decision?ticker=${encodeURIComponent(ticker)}`);
      const thesis=d.thesis||{}, life=d.thesis_lifecycle||{};
      el.innerHTML=`<div class="metric-grid">${metric('Direction',d.direction||d.bias||d.action||'—')}${metric('Decision',d.decision_state||d.state||'—')}${metric('Confidence',d.confidence??d.evidence_score??'—')}${metric('Horizon',d.horizon||d.trade_horizon||'—')}${metric('Setup',d.setup||d.setup_type||'—')}${metric('Lifecycle',life.state||life.status||'—')}</div><div class="narrative" style="margin-top:9px">${escapeHtml(thesis.summary||thesis.primary_thesis||d.rationale||d.narrative||'No decision thesis available.')}</div>`;
    }catch(e){el.innerHTML=errorBox(e.message)}
  }

  function drawChart(data){
    const c=$('priceChart'), ctx=c.getContext('2d'), ratio=window.devicePixelRatio||1, w=c.clientWidth||800,h=230; c.width=w*ratio;c.height=h*ratio;ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,w,h);
    const bars=(data.chart||[]).filter(x=>Number.isFinite(Number(x.close??x.c??x.price))); if(!bars.length){ctx.fillStyle='#8295b3';ctx.font='12px JetBrains Mono';ctx.fillText('No chart data available',20,30);return;}
    const vals=bars.map(x=>Number(x.close??x.c??x.price)), lo=Math.min(...vals),hi=Math.max(...vals),range=Math.max(.01,hi-lo),pad=14;
    ctx.strokeStyle='#1c2b41';ctx.lineWidth=1;for(let i=1;i<4;i++){const y=(h/4)*i;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke()}
    ctx.strokeStyle='#38bdf8';ctx.lineWidth=2;ctx.beginPath();vals.forEach((v,i)=>{const x=pad+i*(w-pad*2)/Math.max(1,vals.length-1), y=h-pad-(v-lo)/range*(h-pad*2);i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();
    ctx.fillStyle='#8295b3';ctx.font='10px JetBrains Mono';ctx.fillText(hi.toFixed(2),5,12);ctx.fillText(lo.toFixed(2),5,h-5);
  }
  async function loadChart(){
    try{const d=await get(`/api/chart_data?ticker=${encodeURIComponent(ticker)}&days=1&tf=${timeframe}`); $('chartMeta').innerHTML=`<span>${escapeHtml(d.ticker||ticker)}</span><span>Close: <b class="blue">${num(d.currentClose)}</b></span><span>High: ${num(d.recentHigh)}</span><span>Low: ${num(d.recentLow)}</span><span>Regime: <b class="${cls(d.regime)}">${escapeHtml(d.regime||'—')}</b></span><span>${escapeHtml(d.updatedAt||'')}</span>`;drawChart(d)}catch(e){$('chartMeta').innerHTML=`<span class="red">${escapeHtml(e.message)}</span>`;drawChart({chart:[]})}
  }

  async function loadFlow(){
    const el=$('flowContent');
    try{const d=await get(`/api/flow/${encodeURIComponent(ticker)}`);el.innerHTML=`<div class="metric-grid">${metric('Stock Price',money(d.stock_price))}${metric('Flow Bias',d.flow_bias||d.bias||d.sentiment||'—')}${metric('Net Premium',money(d.net_premium??d.net_flow??d.premium))}${metric('Call Wall',money(d.call_wall))}${metric('Put Wall',money(d.put_wall))}${metric('Gamma Flip',money(d.active_gamma_flip??d.zero_gamma))}${metric('GEX',d.gex_score??d.gex_status??'—')}${metric('Call Premium',money(d.call_premium??d.calls_premium))}${metric('Put Premium',money(d.put_premium??d.puts_premium))}</div>`}catch(e){el.innerHTML=errorBox(e.message)}
  }

  async function loadStory(){
    const el=$('storyContent');
    try{let d;try{d=await get('/api/market_story')}catch(_){d=await get('/api/story')};const story=d.story||d.market_story||d.narrative||d.summary||d.executive_summary;const arr=d.events||d.timeline||d.bullets||[];el.innerHTML=`<div class="narrative">${escapeHtml(typeof story==='string'?story:(story?.summary||story?.headline||'Market story is not yet available.'))}</div>${Array.isArray(arr)&&arr.length?`<ul class="bullet-list">${arr.slice(0,8).map(x=>`<li>${escapeHtml(typeof x==='string'?x:(x.text||x.event||x.summary||JSON.stringify(x)))}</li>`).join('')}</ul>`:''}`;}catch(e){el.innerHTML=errorBox(e.message)}
  }

  async function loadLevels(){
    const el=$('levelsContent');
    try{const d=await get(`/api/mission_control?ticker=${encodeURIComponent(ticker)}`), p=d.expected_path||{};let above=p.levels_above||p.above||[],below=p.levels_below||p.below||[];if(!above.length&&!below.length){try{const l=await get(`/api/institutional-market-structure/levels?ticker=${encodeURIComponent(ticker)}`);above=l.levels_above||l.above||l.resistance||[];below=l.levels_below||l.below||l.support||[]}catch(_){}}
      const row=x=>`<div class="level-row"><span>${escapeHtml(x.label||x.name||x.type||x.kind||'Level')}</span><strong>${num(x.level??x.price??x.value)}</strong></div>`;
      el.innerHTML=`<div class="level-columns"><div class="level-side"><h3>Above / Resistance</h3>${above.length?above.slice(0,8).map(row).join(''):emptyBox('No levels above')}</div><div class="level-side"><h3>Below / Support</h3>${below.length?below.slice(0,8).map(row).join(''):emptyBox('No levels below')}</div></div>`;
    }catch(e){el.innerHTML=errorBox(e.message)}
  }

  async function loadTape(){
    const el=$('tapeContent');
    try{const d=await get(`/api/flow_tape?tickers=${encodeURIComponent(ticker)}&size=20`), rows=d.rows||[];const s=d.summary||{};el.innerHTML=`<div class="metric-grid">${metric('Tape Bias',s.tape_bias||'—')}${metric('Net Premium',money(s.net_premium))}${metric('Rows',s.row_count??rows.length)}${metric('Sweeps',s.sweep_count??'—')}${metric('Blocks',s.block_count??'—')}${metric('Buy Premium',money(s.buy_premium))}</div><div style="margin-top:8px">${rows.length?rows.slice(0,8).map(r=>`<div class="tape-row"><span>${escapeHtml(r.ticker||ticker)}</span><span class="${cls(r.side||r.sentiment)}">${escapeHtml(r.side||r.sentiment||r.option_type||'—')}</span><span>${escapeHtml(r.classification||r.type||r.trade_type||'Flow')}</span><strong>${money(r.premium??r.total_premium)}</strong></div>`).join(''):emptyBox(d.message||'No qualifying tape rows')}</div>`}catch(e){el.innerHTML=errorBox(e.message)}
  }

  async function loadReplay(){
    const el=$('replayContent');
    try{let d;try{d=await get(`/api/replay/session?ticker=${encodeURIComponent(ticker)}`)}catch(_){d=await get(`/api/replay/status?ticker=${encodeURIComponent(ticker)}`)};const frames=d.frames||d.timeline||d.replays||[];el.innerHTML=`<div class="metric-grid">${metric('Status',d.status||d.state||(d.ok?'READY':'—'))}${metric('Frames',d.frame_count??frames.length??'—')}${metric('Session',d.session_date||d.date||'—')}</div><div style="margin-top:8px">${Array.isArray(frames)&&frames.length?frames.slice(-6).reverse().map(f=>`<div class="replay-row"><span>${escapeHtml(f.frame_time||f.time||f.timestamp||'—')}</span><span class="${cls(f.decision_state||f.state)}">${escapeHtml(f.decision_state||f.state||'Snapshot')}</span><strong>${num(f.price)}</strong></div>`).join(''):emptyBox(d.message||'No replay frames available')}</div>`}catch(e){el.innerHTML=errorBox(e.message)}
  }

  async function loadSignals(){
    const el=$('signalContent');
    try{const [p,a]=await Promise.allSettled([get('/api/signal_log'),get('/api/apex_signals?limit=20')]);const pine=p.status==='fulfilled'?(p.value.signals||[]):[], apex=a.status==='fulfilled'?(a.value.signals||[]):[];const rows=[...apex.map(x=>({...x,_src:'APEX'})),...pine.map(x=>({...x,_src:'PINE'}))].slice(0,10);el.innerHTML=`<div class="metric-grid">${metric('APEX Signals',apex.length)}${metric('Pine Signals',pine.length)}${metric('Displayed',rows.length)}</div><div style="margin-top:8px">${rows.length?rows.map(r=>`<div class="signal-row"><span>${escapeHtml(r._src)}</span><span class="${cls(r.side||r.direction||r.action)}">${escapeHtml(r.side||r.direction||r.action||'—')}</span><span>${escapeHtml(r.ticker||'SPX')} ${escapeHtml(r.status||r.outcome||r.apex_auction||'')}</span><strong>${num(r.price??r.entry_price)}</strong></div>`).join(''):emptyBox('No signals recorded')}</div>`}catch(e){el.innerHTML=errorBox(e.message)}
  }

  async function refreshAll(){
    setRefresh(true,'Refreshing…');
    const tasks=[loadMission(),loadExecution(),loadAnalysis(),loadChart(),loadFlow(),loadStory(),loadLevels(),loadTape(),loadReplay(),loadSignals()];
    const rs=await Promise.allSettled(tasks), failures=rs.filter(x=>x.status==='rejected').length;
    setRefresh(failures===0, failures?`${failures} component refresh errors`:`Live · ${new Date().toLocaleTimeString()}`);
  }
  $('tickerSelect').addEventListener('change',e=>{ticker=e.target.value;refreshAll()});
  $('refreshAll').addEventListener('click',refreshAll);
  document.querySelectorAll('.chart-controls button').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('.chart-controls button').forEach(x=>x.classList.remove('active'));b.classList.add('active');timeframe=Number(b.dataset.tf);loadChart()}));
  window.addEventListener('resize',()=>loadChart());
  updateClock();setInterval(updateClock,1000);refreshAll();refreshTimer=setInterval(refreshAll,15000);
})();

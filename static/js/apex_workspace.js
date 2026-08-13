(()=>{
const VERSION='42.0';
const NAV=[
['Favorites',[]],
['Command',[['Command Center','/command_center','APEX 42 unified session workspace'],['Institutional OS','/apex_os','Institutional OS'],['Scanner','/scanner','Market scanner'],['Trade Command','/apex_os/trade_command','Live decision and execution'],['Execution OS','/apex_os/execution','Execution readiness'],['Morning Readiness','/apex_os/readiness','Pre-market checks']]],
['Trading',[['Flow / GEX','/flow','Options flow and dealer exposure'],['Chart','/chart','Synchronized market chart'],['Premium Discipline','/apex_os/premium_discipline','Premium scalp command center'],['Trading Desk','/apex_os/institutional_trading_desk','Institutional trading workspace'],['Execution Intelligence','/apex_os/institutional_execution_intelligence','Execution analytics']]],
['Intelligence',[['Market State','/apex_os/institutional_market_state','Market regime and state'],['Decision Intelligence','/apex_os/decision_intelligence','Decision core'],['Playbook Engine','/apex_os/institutional_playbooks','Playbook matching'],['Strategy Intelligence','/apex_os/strategy_intelligence','Strategy analytics'],['Similarity Lab','/apex_os/institutional_similarity','Historical similarity'],['Research Lab','/apex_os/research_lab','Institutional research']]],
['Learning',[['Assistant','/assistant','APEX assistant'],['Adaptive Learning','/apex_os/adaptive_learning','Learning engine'],['Replay Laboratory','/apex_os/institutional_replay','Replay and review'],['Cross Examination','/apex_os/cross_examination','Challenge decisions'],['Confidence Attribution','/apex_os/confidence_attribution','Confidence drivers'],['Evidence Graph','/apex_os/evidence_graph','Decision evidence']]],
['Operations',[['Operations Center','/apex_os/operations','System operations'],['Data Quality','/apex_os/data_quality','Data quality dashboard'],['Historical Readiness','/apex_os/historical_readiness','History coverage'],['Shadow Validation','/apex_os/shadow_validation','Shadow testing'],['Production Governance','/apex_os/production_governance','Production controls'],['Release Manager','/apex_os/release_manager','Release governance'],['Offline Optimization','/apex_os/offline_optimization','Offline optimization']]]];
const MOBILE_TABS=[['Home','⌂','/command_center'],['Trade','⚡','/apex_os/trade_command'],['Market','◈','/apex_os/institutional_market_state'],['AI','◆','/assistant'],['More','☰','#more']];
const PRESETS={scanner:'/command_center',find:'/scanner',execution:'/apex_os/trade_command',manage:'/apex_os',review:'/apex_os/institutional_replay'};
const all=()=>NAV.flatMap(([g,x])=>x.map(v=>[g,...v]));
const path=location.pathname.replace(/\/$/,'')||'/';
const safeJson=(key,fallback)=>{try{return JSON.parse(localStorage.getItem(key)||JSON.stringify(fallback))}catch{return fallback}};
const fav=()=>safeJson('ap40:favorites',[]); const setFav=x=>localStorage.setItem('ap40:favorites',JSON.stringify(x));
const deviceKey=()=>matchMedia('(max-width:600px)').matches?'phone':matchMedia('(max-width:1024px)').matches?'tablet':matchMedia('(min-width:1700px)').matches?'ultrawide':'desktop';
const settings=()=>safeJson(`ap41:${deviceKey()}:settings`,{compact:false,tradeMonitor:true,lastPreset:'execution'});
const saveSettings=x=>localStorage.setItem(`ap41:${deviceKey()}:settings`,JSON.stringify(x));
function icon(g){return {Command:'⌂',Trading:'⚡',Intelligence:'◈',Learning:'◆',Operations:'⚙',Favorites:'★'}[g]||'•'}
function link(g,n,u,d){const active=path===u.replace(/\/$/,'');return `<a class="ap41-link ${active?'active':''}" href="${u}" title="${d}"><span>${icon(g)}</span><span>${n}</span><button class="ap41-star ${fav().includes(u)?'on':''}" data-fav="${u}" aria-label="Favorite ${n}">★</button></a>`}
function applyDeviceClass(){document.documentElement.dataset.apexDevice=deviceKey();document.body.classList.toggle('ap41-compact',!!settings().compact)}
function render(){
 applyDeviceClass(); document.body.classList.add('ap41-ready');
 const sidebar=document.createElement('aside');sidebar.className='ap41-sidebar';sidebar.id='ap41Sidebar';
 const favorites=fav().map(u=>all().find(x=>x[2]===u)).filter(Boolean);
 sidebar.innerHTML=`<div class="ap41-brand"><b>APEX</b><span>42</span><small>${deviceKey()}</small></div><div class="ap41-workflows"><button data-preset="scanner">Find Trade</button><button data-preset="execution">Execute</button><button data-preset="manage">Manage</button><button data-preset="review">Review</button></div>`+NAV.map(([g,items])=>{if(g==='Favorites')items=favorites.map(x=>[x[1],x[2],x[3]]);if(!items.length)return'';return `<section class="ap41-section"><button>${g}<span>⌄</span></button><div>${items.map(x=>link(g,...x)).join('')}</div></section>`}).join('');
 document.body.prepend(sidebar);
 const current=all().find(x=>path===x[2].replace(/\/$/,''));
 const top=document.createElement('header');top.className='ap41-topbar';top.innerHTML=`<button class="ap41-menu" id="ap41Menu">☰</button><div class="ap41-crumb">APEX / ${current?current[0]+' / <strong>'+current[1]+'</strong>':'<strong>Workspace</strong>'}</div><div class="ap41-device">${deviceKey()}</div><button class="ap41-search" id="ap41Search">Search <span>Ctrl K</span></button>`;document.body.prepend(top);
 const bottom=document.createElement('nav');bottom.className='ap41-bottom';bottom.innerHTML=MOBILE_TABS.map(([n,i,u])=>`<a href="${u}" data-mobile="${n.toLowerCase()}" class="${u!=='#more'&&path===u?'active':''}"><span>${i}</span><small>${n}</small></a>`).join('');document.body.append(bottom);
 const fab=document.createElement('button');fab.className='ap41-fab';fab.id='ap41Fab';fab.innerHTML='⚡';fab.setAttribute('aria-label','Open quick actions');document.body.append(fab);
 const sheet=document.createElement('div');sheet.className='ap41-sheet';sheet.id='ap41Sheet';sheet.innerHTML=`<div><i></i><h3>Quick actions</h3><button data-preset="scanner">Find Trade</button><button data-preset="execution">Open Execution</button><button data-preset="review">Review Session</button><button id="ap41Compact">Toggle Compact Mode</button><button id="ap41MonitorToggle">Toggle Trade Monitor</button></div>`;document.body.append(sheet);
 const monitor=document.createElement('aside');monitor.className='ap41-monitor';monitor.id='ap41Monitor';monitor.innerHTML=`<button id="ap41MonitorClose">×</button><span>TRADE MONITOR</span><strong>NO ACTIVE TRADE</strong><small>Execution state will remain visible here while navigating APEX.</small><a href="/apex_os/trade_command">Open Trade Command</a>`;document.body.append(monitor);
 const ov=document.createElement('div');ov.className='ap41-overlay';ov.id='ap41Overlay';ov.innerHTML='<div class="ap41-palette"><input id="ap41Input" placeholder="Search APEX pages, tools, and workflows…" autocomplete="off"><div id="ap41Results"></div></div>';document.body.append(ov);
 bind(sidebar,ov,sheet,monitor);search(); syncMonitor();
}
function bind(sidebar,ov,sheet,monitor){
 document.querySelectorAll('.ap41-section>button').forEach(b=>b.onclick=()=>b.parentElement.classList.toggle('collapsed'));
 document.querySelectorAll('[data-preset]').forEach(b=>b.onclick=()=>{const p=b.dataset.preset;saveSettings({...settings(),lastPreset:p});location.href=PRESETS[p]});
 document.querySelectorAll('[data-fav]').forEach(b=>b.onclick=e=>{e.preventDefault();e.stopPropagation();let f=fav(),u=b.dataset.fav;setFav(f.includes(u)?f.filter(x=>x!==u):[...f,u]);refresh()});
 document.getElementById('ap41Menu').onclick=()=>sidebar.classList.toggle('open');
 document.getElementById('ap41Search').onclick=openPalette; ov.onclick=e=>{if(e.target===ov)closePalette()}; document.getElementById('ap41Input').oninput=search;
 document.querySelector('[data-mobile="more"]').onclick=e=>{e.preventDefault();sheet.classList.add('open')};
 document.getElementById('ap41Fab').onclick=()=>sheet.classList.add('open'); sheet.onclick=e=>{if(e.target===sheet)sheet.classList.remove('open')};
 document.getElementById('ap41Compact').onclick=()=>{const s=settings();saveSettings({...s,compact:!s.compact});applyDeviceClass()};
 document.getElementById('ap41MonitorToggle').onclick=()=>{const s=settings();saveSettings({...s,tradeMonitor:!s.tradeMonitor});syncMonitor();sheet.classList.remove('open')};
 document.getElementById('ap41MonitorClose').onclick=()=>{saveSettings({...settings(),tradeMonitor:false});syncMonitor()};
 document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();openPalette()}if(e.key==='Escape'){closePalette();sheet.classList.remove('open');sidebar.classList.remove('open')}});
 let startX=0;document.addEventListener('touchstart',e=>{startX=e.changedTouches[0].clientX},{passive:true});document.addEventListener('touchend',e=>{const dx=e.changedTouches[0].clientX-startX;if(startX<24&&dx>70)sidebar.classList.add('open');if(dx<-90)sidebar.classList.remove('open')},{passive:true});
 addEventListener('resize',applyDeviceClass,{passive:true});
}
function syncMonitor(){const m=document.getElementById('ap41Monitor');if(m)m.classList.toggle('show',!!settings().tradeMonitor&&deviceKey()!=='phone')}
function refresh(){document.querySelectorAll('.ap41-sidebar,.ap41-topbar,.ap41-bottom,.ap41-fab,.ap41-sheet,.ap41-monitor,.ap41-overlay').forEach(x=>x.remove());document.body.classList.remove('ap41-ready');render()}
function openPalette(){document.getElementById('ap41Overlay').classList.add('open');setTimeout(()=>document.getElementById('ap41Input').focus(),0)}
function closePalette(){document.getElementById('ap41Overlay').classList.remove('open')}
function search(){const input=document.getElementById('ap41Input');if(!input)return;const q=(input.value||'').toLowerCase();const rows=all().filter(x=>!q||x.join(' ').toLowerCase().includes(q)).slice(0,20);document.getElementById('ap41Results').innerHTML=rows.map(x=>`<a href="${x[2]}"><span>${x[1]}</span><small>${x[0]} · ${x[3]}</small></a>`).join('')||'<div class="ap41-empty">No matching workspace pages</div>'}
window.APEX41={version:VERSION,device:deviceKey,presets:PRESETS};
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',render);else render();
})();

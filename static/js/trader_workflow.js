(function(){
  'use strict';
  const text=(id,fallback='—')=>{const el=document.getElementById(id);const v=(el&&el.textContent||'').trim();return v&&v!=='WARMING'?v:fallback};
  const set=(id,value)=>{const el=document.getElementById(id);if(el)el.textContent=value||'—'};
  function normalizeDecision(value){const v=String(value||'').toUpperCase().replace(/_/g,' ');if(/CALL|BULL|LONG/.test(v))return 'CALL BIAS';if(/PUT|BEAR|SHORT/.test(v))return 'PUT BIAS';if(/STAND|AVOID|NO TRADE|BLOCK/.test(v))return 'STAND ASIDE';return v||'OBSERVE';}
  function tone(value){const v=String(value||'').toUpperCase();if(/CALL|BULL|PASS|READY|POSITIVE|ACCEPT/.test(v))return 'good';if(/PUT|BEAR|FAIL|BLOCK|NEGATIVE|REJECT/.test(v))return 'bad';return 'neutral';}
  function syncCockpit(){
    set('tcDecision',normalizeDecision(text('iwDecision','OBSERVE')));
    set('tcSummary',text('iwHeadline','Waiting for a complete institutional decision.'));
    set('tcConfidence',text('iwConfidence','—'));
    set('tcEntry',text('iwEntry','—')); set('tcStop',text('iwStop','—')); set('tcTarget',text('iwTp1','—'));
    set('tcSize',text('iwReadiness','—')); set('tcBias',text('iwBias','NEUTRAL')); set('tcStrategy',text('iwStrategy','NO TRADE'));
    const evidence=[['tcDealer',text('ribbonDealer','Dealer: —')],['tcFlow',text('ribbonFlow','Flow: —')],['tcAuction',text('ribbonAuction','Auction: —')]];
    evidence.forEach(([id,v])=>{set(id,v);const el=document.getElementById(id);if(el){el.className='tc-chip '+tone(v)}});
  }
  function hidePhaseLabels(root=document){
    root.querySelectorAll('.label').forEach(el=>{if(/TRADE DIRECTOR PHASE\s+\d+/i.test(el.textContent||'')){el.classList.add('phase-label-hidden')}});
  }
  function init(){
    const cockpit=document.getElementById('traderCockpit');
    if(cockpit){syncCockpit();const source=document.getElementById('iwBanner');if(source)new MutationObserver(syncCockpit).observe(source,{subtree:true,childList:true,characterData:true});setInterval(syncCockpit,2500)}
    hidePhaseLabels();new MutationObserver(m=>{m.forEach(x=>x.addedNodes.forEach(n=>{if(n.nodeType===1)hidePhaseLabels(n)}))}).observe(document.body,{subtree:true,childList:true});
  }
  document.readyState==='loading'?document.addEventListener('DOMContentLoaded',init):init();
})();

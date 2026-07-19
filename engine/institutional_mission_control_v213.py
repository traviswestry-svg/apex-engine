"""APEX 21.3 — compact Mission Control 2.0 summary."""
from datetime import datetime, timezone
from typing import Any, Dict
from .institutional_workspace_v212 import build_workspace
from .institutional_trading_brain_v230 import build_institutional_trading_brain
from .institutional_regime_intelligence_v231 import build_regime_intelligence
from .institutional_forecast_engine_v232 import build_institutional_forecast
from .institutional_playbook_engine_v233 import build_institutional_playbooks
from .continuous_learning_calibration_v234 import build_continuous_learning
from .institutional_ai_trading_coach_v235 import build_trading_coach, behavioral_scorecard
VERSION="14.3.0_INSTITUTIONAL_MISSION_CONTROL_2"

def build_mission_control(last:Dict[str,Any], configuration=None, dependencies=None)->Dict[str,Any]:
    ws=build_workspace(last)
    cfg=configuration() if callable(configuration) else (configuration or {})
    dep=dependencies() if callable(dependencies) else (dependencies or {})
    execution=ws['workspace']['execution_plan']; decision=ws['workspace']['decision']
    brain=build_institutional_trading_brain(last)
    regime=build_regime_intelligence(last)
    forecast=build_institutional_forecast(last)
    playbooks=build_institutional_playbooks(last)
    learning=build_continuous_learning(last)
    coach=build_trading_coach(last)
    coach_scorecard=behavioral_scorecard(str(last.get("ticker") or "SPX"))
    groups={
      'MARKET_STATE':{'state':'PASS' if decision.get('evidence_coverage',0)>=60 else 'WARNING','summary':decision.get('headline')},
      'DECISION':{'state':'PASS' if decision.get('decision')=='TRADE_CANDIDATE' else 'WARNING','summary':decision.get('decision')},
      'TRADING_BRAIN':{'state':'PASS' if brain.get('execution_readiness',{}).get('eligible') else 'WARNING','summary':brain.get('headline')},
      'REGIME_INTELLIGENCE':{'state':'PASS' if regime.get('transition',{}).get('state') in ('STABLE','CONFIRMED') else 'WARNING','summary':f"{regime.get('primary_regime')} · {regime.get('confidence')}%"},
      'INSTITUTIONAL_FORECAST':{'state':'PASS' if forecast.get('status')=='ACTIVE' else 'WARNING','summary':f"{forecast.get('primary_scenario')} · {forecast.get('forecast_confidence')}%"},
      'INSTITUTIONAL_PLAYBOOKS':{'state':'PASS' if playbooks.get('execution_readiness',{}).get('eligible') else 'WARNING','summary':playbooks.get('selected_playbook',{}).get('playbook_id')},
      'EXECUTION':{'state':'PASS' if execution.get('state')=='READY' else 'BLOCKED','summary':execution.get('state')},
      'CONFIGURATION':{'state':cfg.get('state','UNKNOWN'),'summary':f"{cfg.get('configured','—')} configured"},
      'DEPENDENCIES':{'state':dep.get('state','UNKNOWN'),'summary':f"{dep.get('configured','—')}/{dep.get('total','—')} ready"},
      'LEARNING':{'state':'PASS' if learning.get('status')=='ACTIVE' else 'INFO','summary':f"{learning.get('status')} · {learning.get('calibration',{}).get('samples',0)} outcomes"},
      'TRADING_COACH':{'state':'PASS' if coach.get('coaching',{}).get('recommendation')=='TAKE' else 'INFO','summary':f"{coach.get('phase')} · {coach.get('coaching',{}).get('recommendation')}"},
      'MEMORY':{'state':'INFO','summary':'Dormant-safe session memory'},
      'HARDENING':{'state':'PASS','summary':'Route, scanner, persistence, and snapshot governance active'},
      'RISK':{'state':'PASS' if not decision.get('execution_eligible') else 'WARNING','summary':'Human confirmation required'},
      'BROKER':{'state':'BLOCKED','summary':'Mutation remains disabled by governance'},
    }
    overall='BLOCKED' if any(x['state'] in ('BLOCKED','BLOCKING') for x in groups.values()) else 'WARNING' if any(x['state'] in ('WARNING','UNKNOWN') for x in groups.values()) else 'PASS'
    return {'ok':True,'version':VERSION,'evaluated_at':datetime.now(timezone.utc).isoformat(),'state':overall,'groups':groups,
      'decision_banner':ws['decision_banner'],'institutional_playbooks':{'selected_playbook':playbooks.get('selected_playbook'),'execution_readiness':playbooks.get('execution_readiness'),'context':playbooks.get('context')},'institutional_forecast':{'primary_scenario':forecast.get('primary_scenario'),'forecast_confidence':forecast.get('forecast_confidence'),'scenario_probabilities':forecast.get('scenario_probabilities'),'uncertainty_bands':forecast.get('uncertainty_bands'),'timing_guidance':forecast.get('timing_guidance')},'regime_intelligence':{'primary_regime':regime.get('primary_regime'),'secondary_regime':regime.get('secondary_regime'),'confidence':regime.get('confidence'),'transition':regime.get('transition'),'risk_posture':regime.get('risk_posture')},'continuous_learning':{'status':learning.get('status'),'calibration':learning.get('calibration'),'confidence':learning.get('confidence'),'drift':learning.get('drift'),'recommendations':learning.get('recommendations')},'trading_coach':{'phase':coach.get('phase'),'coaching':coach.get('coaching'),'context':coach.get('context'),'scorecard':coach_scorecard},'trading_brain':{'headline':brain.get('headline'),'primary_thesis':brain.get('primary_thesis'),'alternate_scenario':brain.get('alternate_scenario'),'confidence':brain.get('calibrated_confidence'),'conflicts':brain.get('conflicting_evidence'),'execution_readiness':brain.get('execution_readiness')},'execution_readiness':ws['execution_readiness'],'drilldowns':{
       'decision':'/api/institutional-decision/diagnostics','volume':'/api/institutional-volume-profile/diagnostics','execution':'/api/execution-optimizer/plan','strategy':'/api/strategy-intelligence/diagnostics','configuration':'/api/configuration/diagnostics','dependencies':'/api/dependencies/diagnostics','memory':'/api/market-memory/diagnostics','hardening':'/api/pre23-hardening/status','snapshot':'/api/institutional-snapshot/status','trading_brain':'/api/trading-brain/diagnostics','regime_intelligence':'/api/regime-intelligence/diagnostics','institutional_forecast':'/api/institutional-forecast/diagnostics','institutional_playbooks':'/api/institutional-playbooks/diagnostics','continuous_learning':'/api/continuous-learning/diagnostics','trading_coach':'/api/trading-coach/diagnostics'},
      'guardrails':ws['guardrails']}

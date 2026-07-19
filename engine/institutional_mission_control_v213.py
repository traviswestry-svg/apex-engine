"""APEX 21.3 — compact Mission Control 2.0 summary."""
from datetime import datetime, timezone
from typing import Any, Dict
from .institutional_workspace_v212 import build_workspace
VERSION="14.3.0_INSTITUTIONAL_MISSION_CONTROL_2"

def build_mission_control(last:Dict[str,Any], configuration=None, dependencies=None)->Dict[str,Any]:
    ws=build_workspace(last)
    cfg=configuration() if callable(configuration) else (configuration or {})
    dep=dependencies() if callable(dependencies) else (dependencies or {})
    execution=ws['workspace']['execution_plan']; decision=ws['workspace']['decision']
    groups={
      'MARKET_STATE':{'state':'PASS' if decision.get('evidence_coverage',0)>=60 else 'WARNING','summary':decision.get('headline')},
      'DECISION':{'state':'PASS' if decision.get('decision')=='TRADE_CANDIDATE' else 'WARNING','summary':decision.get('decision')},
      'EXECUTION':{'state':'PASS' if execution.get('state')=='READY' else 'BLOCKED','summary':execution.get('state')},
      'CONFIGURATION':{'state':cfg.get('state','UNKNOWN'),'summary':f"{cfg.get('configured','—')} configured"},
      'DEPENDENCIES':{'state':dep.get('state','UNKNOWN'),'summary':f"{dep.get('configured','—')}/{dep.get('total','—')} ready"},
      'LEARNING':{'state':'INFO','summary':'Review and replay governed'},
      'MEMORY':{'state':'INFO','summary':'Dormant-safe session memory'},
      'RISK':{'state':'PASS' if not decision.get('execution_eligible') else 'WARNING','summary':'Human confirmation required'},
      'BROKER':{'state':'BLOCKED','summary':'Mutation remains disabled by governance'},
    }
    overall='BLOCKED' if any(x['state'] in ('BLOCKED','BLOCKING') for x in groups.values()) else 'WARNING' if any(x['state'] in ('WARNING','UNKNOWN') for x in groups.values()) else 'PASS'
    return {'ok':True,'version':VERSION,'evaluated_at':datetime.now(timezone.utc).isoformat(),'state':overall,'groups':groups,
      'decision_banner':ws['decision_banner'],'execution_readiness':ws['execution_readiness'],'drilldowns':{
       'decision':'/api/institutional-decision/diagnostics','volume':'/api/institutional-volume-profile/diagnostics','execution':'/api/execution-optimizer/plan','strategy':'/api/strategy-intelligence/diagnostics','configuration':'/api/configuration/diagnostics','dependencies':'/api/dependencies/diagnostics','memory':'/api/market-memory/diagnostics'},
      'guardrails':ws['guardrails']}

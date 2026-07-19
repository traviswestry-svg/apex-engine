"""Read-only routes for APEX 21.1-21.3."""
from flask import jsonify
from .institutional_volume_profile_v211 import build_volume_profile_intelligence
from .institutional_workspace_v212 import build_workspace
from .institutional_mission_control_v213 import build_mission_control

def register_institutional_workspace_routes(app,last_result_provider,configuration_status_provider=None,dependency_status_provider=None):
 def cur():
  value=last_result_provider() if callable(last_result_provider) else {}
  return value if isinstance(value,dict) else {}
 @app.get('/api/institutional-volume-profile/status')
 def ivp_status(): return jsonify(build_volume_profile_intelligence(cur()))
 @app.get('/api/institutional-volume-profile/diagnostics')
 def ivp_diag(): return jsonify(build_volume_profile_intelligence(cur()))
 @app.get('/api/institutional-volume-profile/levels')
 def ivp_levels():
  x=build_volume_profile_intelligence(cur()); return jsonify({'ok':True,'version':x['version'],'levels':x['levels'],'ranked_levels':x['ranked_levels'],'legend':x['legend']})
 @app.get('/api/institutional-workspace/status')
 def workspace_status(): return jsonify(build_workspace(cur()))
 @app.get('/api/institutional-workspace/layout')
 def workspace_layout():
  x=build_workspace(cur()); return jsonify({'ok':True,'version':x['version'],'layout':x['workspace']['layout'],'context_layout':x['context_layout']})
 @app.get('/api/mission-control-v2/status')
 def mc_status(): return jsonify(build_mission_control(cur(),configuration_status_provider,dependency_status_provider))
 @app.get('/api/mission-control-v2/diagnostics')
 def mc_diag(): return jsonify(build_mission_control(cur(),configuration_status_provider,dependency_status_provider))

"""APEX 11.4-12.3 read-mostly governed API and dashboard routes."""
from __future__ import annotations
from flask import jsonify, render_template, request
from . import institutional_governance as gov
from .institutional_narrative import build_institutional_narrative, build_consensus_gauge, build_conviction
from .institutional_decision_object import build_canonical_institutional_decision
from .decision_review import build_decision_review, build_replay
from . import institutional_evidence as evidence
from . import institutional_data_quality as data_quality
from . import historical_readiness
from . import institutional_similarity as institutional_similarity
from . import institutional_research
from . import offline_weight_optimization as weight_opt
from . import shadow_validation
from . import production_governance
from . import canary_deployment
from . import institutional_release_manager
from . import decision_intelligence_core
from . import confidence_attribution_engine
from . import institutional_evidence_graph
from . import decision_intelligence_center
from . import institutional_replay_2
from . import cross_examination_engine
from . import institutional_market_state_engine as imse
from . import institutional_playbook_engine as ipe
from . import prediction_confidence_calibration as pcce
from . import institutional_execution_intelligence as iei
from . import institutional_research_lab as irl
from . import institutional_order_flow_intelligence as iofi
from . import live_mission_control as lmc
from . import adaptive_trade_management as atm
from . import portfolio_risk_intelligence as pri
from . import explainable_intelligence_assistant as eia
from . import performance_intelligence as pi
from . import live_operations as lo
from . import strategy_promotion_governance as spg
from . import broker_synchronized_position_state as bsps
from . import confirmation_gated_execution as cge
from . import sandbox_execution_validation as sev
from . import institutional_autonomous_desk as iad
from . import institutional_trading_desk_ux as itdux
from . import adaptive_intelligence as ai18


def register_institutional_roadmap_routes(app, *, last_result_provider):
    gov.init_db()
    def current():
        v=last_result_provider() or {}; return v if isinstance(v,dict) else {}
    def j(payload, code=200): return jsonify(payload), code

    # Required aliases and decomposed narrative APIs.
    @app.get('/api/narrative')
    @app.get('/api/narrative/story')
    def roadmap_narrative(): return jsonify({'ok':True,**build_institutional_narrative(current(),session_state=request.args.get('session'))})
    @app.get('/api/narrative/thesis')
    def roadmap_thesis():
        n=build_institutional_narrative(current()); return jsonify({'ok':True,'status':n['freshness']['status'],'primary_thesis':n['primary_thesis'],'alternate_thesis':n['alternate_thesis']})
    @app.get('/api/narrative/risks')
    def roadmap_risks():
        n=build_institutional_narrative(current()); return jsonify({'ok':True,'status':n['freshness']['status'],'risk_drivers':n['risk_drivers']})
    @app.get('/api/narrative/invalidation')
    def roadmap_invalidation():
        n=build_institutional_narrative(current()); return jsonify({'ok':True,'status':n['freshness']['status'],'invalidation':n['invalidation_conditions']})
    @app.get('/api/consensus')
    @app.get('/api/consensus/contributors')
    def roadmap_consensus(): return jsonify({'ok':True,**build_consensus_gauge(current())})
    @app.get('/api/consensus/history')
    def roadmap_consensus_history(): return jsonify({'ok':True,'status':'COLLECTING','events':[],'message':'Consensus history is populated only by persisted real decision snapshots.'})
    @app.get('/api/conviction')
    @app.get('/api/conviction/contributors')
    def roadmap_conviction(): return jsonify({'ok':True,**build_conviction(current())})
    @app.get('/api/institutional-decision/<recommendation_id>')
    def roadmap_decision_by_id(recommendation_id):
        review=build_decision_review(recommendation_id)
        if review is None: return j({'ok':False,'status':'UNAVAILABLE','error':'not_found'},404)
        return jsonify({'ok':True,**build_canonical_institutional_decision(current(),recommendation_id=recommendation_id)})
    @app.get('/api/recommendation/<recommendation_id>/review')
    @app.get('/api/recommendation/<recommendation_id>/timeline')
    @app.get('/api/recommendation/<recommendation_id>/decision')
    @app.get('/api/recommendation/<recommendation_id>/explanation')
    def roadmap_recommendation_review(recommendation_id):
        p=build_decision_review(recommendation_id); return j({'ok':False,'status':'UNAVAILABLE','error':'not_found'},404) if p is None else jsonify({'ok':True,**p})
    @app.get('/api/replay/narrative')
    @app.get('/api/replay/consensus')
    @app.get('/api/replay/thesis')
    @app.get('/api/replay/decision')
    def roadmap_replay_alias():
        rid=request.args.get('recommendation_id',''); p=build_replay(rid) if rid else None
        return jsonify({'ok':True,**(p or {'status':'UNAVAILABLE','frames':[],'message':'recommendation_id is required or no replay exists'})})

    # Historical intelligence.
    @app.get('/api/history/status')
    @app.get('/api/history/coverage')
    @app.get('/api/history/quality')
    @app.get('/api/history/calibration-readiness')
    def roadmap_history_status(): return jsonify({'ok':True,**gov.history_report()})
    @app.get('/api/history/scorecard')
    @app.get('/api/history/confidence-calibration')
    def roadmap_history_scorecard(): return jsonify({'ok':True,**gov.scorecard()})
    @app.post('/api/history/outcomes')
    def roadmap_outcome_ingest():
        p=gov.ingest_outcome(request.get_json(silent=True) or {}); return j(p,201 if p.get('ok') else 409)

    # Similarity and research.
    @app.get('/api/research/status')
    def roadmap_research_status():
        return jsonify({'ok':True,**gov.research_status(),'institutional_similarity':institutional_similarity.status(),'institutional_research':institutional_research.status()})
    @app.get('/api/research/clusters')
    def roadmap_research_clusters():
        return jsonify({'ok':True,'status':'COLLECTING','clusters':[],'message':'Clustering hooks are available, but no production clusters are published without validated research evidence.'})
    @app.get('/api/research/findings')
    def roadmap_research_findings():
        return jsonify({'ok':True,**institutional_research.status(),'findings':institutional_research.findings(limit=int(request.args.get('limit',100)))})
    @app.get('/api/research/findings/<finding_id>')
    def roadmap_research_finding(finding_id):
        p=institutional_research.findings(finding_id=finding_id)
        return j({'ok':False,'status':'UNAVAILABLE','error':'not_found'},404) if p is None else jsonify({'ok':True,'status':'READY','finding':p})
    @app.post('/api/research/generate')
    def roadmap_research_generate():
        b=request.get_json(silent=True) or {}; p=institutional_research.generate(actor=str(b.get('actor') or 'API'))
        return j(p,201 if p.get('created') else 200)
    @app.get('/api/research/comparisons')
    def roadmap_research_comparisons():
        return jsonify(institutional_research.comparisons(request.args.get('dimension','family')))
    @app.get('/api/research/runs')
    def roadmap_research_runs():
        return jsonify({'ok':True,**institutional_research.status(),'runs':institutional_research.runs(int(request.args.get('limit',100)))})
    @app.get('/api/research/similarity')
    def roadmap_research_similarity():
        vid=(request.args.get('recommendation_id') or request.args.get('vector_id') or '').strip()
        if not vid: return jsonify({'ok':True,'status':'UNAVAILABLE','available':False,'matches':[],'reason':'recommendation_id or vector_id required'})
        if institutional_similarity.get_vector(vid): return jsonify({'ok':True,**institutional_similarity.search(vid,top_k=int(request.args.get('top_k',10)),as_of=request.args.get('as_of'))})
        return jsonify({'ok':True,**gov.similarity(vid,int(request.args.get('top_k',10)),request.args.get('as_of'))})
    @app.get('/api/research/similarity/<vector_id>')
    def roadmap_research_similarity_id(vector_id):
        if institutional_similarity.get_vector(vector_id): return jsonify({'ok':True,**institutional_similarity.search(vector_id,top_k=int(request.args.get('top_k',10)),as_of=request.args.get('as_of'))})
        return jsonify({'ok':True,**gov.similarity(vector_id,int(request.args.get('top_k',10)),request.args.get('as_of'))})

    # Governed adaptive learning.
    @app.get('/api/learning/status')
    def roadmap_learning_status(): return jsonify({'ok':True,**gov.learning_status()})
    @app.get('/api/learning/readiness')
    def roadmap_learning_readiness(): return jsonify({'ok':True,**gov.readiness_gates()})
    @app.get('/api/learning/candidates')
    def roadmap_learning_candidates(): return jsonify({'ok':True,'status':gov.learning_status()['status'],'candidates':gov.candidates()})
    @app.get('/api/learning/candidates/<candidate_id>')
    def roadmap_learning_candidate(candidate_id):
        p=gov.candidates(candidate_id); return j({'ok':False,'status':'UNAVAILABLE','error':'not_found'},404) if p is None else jsonify({'ok':True,'candidate':p,'evaluations':gov.evaluations(candidate_id),'approvals':gov.approvals(candidate_id),'shadow_results':gov.shadows(candidate_id)})
    @app.post('/api/learning/candidates')
    def roadmap_create_candidate():
        b=request.get_json(silent=True) or {}; return j({'ok':True,**gov.register_candidate(str(b.get('candidate_type') or 'WEIGHT_OPTIMIZATION'),b.get('config') or {},dataset_hash=b.get('dataset_hash'),baseline_version=b.get('baseline_version'),metrics=b.get('metrics'),limitations=b.get('limitations'),actor=str(b.get('actor') or 'API'))},201)
    @app.post('/api/learning/candidates/<candidate_id>/submit')
    def roadmap_submit_candidate(candidate_id):
        b=request.get_json(silent=True) or {}; p=gov.submit_candidate(candidate_id,actor=str(b.get('actor') or 'API'),note=str(b.get('note') or '')); return j(p,200 if p.get('ok') else 409)
    @app.post('/api/learning/candidates/<candidate_id>/evaluate')
    def roadmap_evaluate_candidate(candidate_id):
        b=request.get_json(silent=True) or {}; p=gov.record_offline_evaluation(candidate_id,b,actor=str(b.get('actor') or 'API')); return j(p,201 if p.get('ok') else 409)
    @app.post('/api/learning/candidates/<candidate_id>/approve-shadow')
    def roadmap_approve(candidate_id):
        b=request.get_json(silent=True) or {}; p=gov.approve_candidate(candidate_id,actor=str(b.get('actor') or 'API'),note=str(b.get('note') or '')); return j(p,200 if p.get('ok') else 409)
    @app.post('/api/learning/candidates/<candidate_id>/reject')
    def roadmap_reject(candidate_id):
        b=request.get_json(silent=True) or {}; p=gov.reject_candidate(candidate_id,actor=str(b.get('actor') or 'API'),note=str(b.get('note') or '')); return j(p,200 if p.get('ok') else 404)
    @app.post('/api/learning/candidates/<candidate_id>/shadow')
    def roadmap_shadow_observation(candidate_id):
        b=request.get_json(silent=True) or {}; p=gov.record_shadow_result(candidate_id,b.get('production') or {},b.get('candidate') or {},b.get('comparison') or {},data_quality=str(b.get('data_quality') or 'UNKNOWN'),observed_at=b.get('observed_at'),actor=str(b.get('actor') or 'API')); return j(p,201 if p.get('ok') else 409)
    @app.post('/api/learning/candidates/<candidate_id>/rollback')
    def roadmap_rollback(candidate_id):
        b=request.get_json(silent=True) or {}; p=gov.rollback(candidate_id,actor=str(b.get('actor') or 'API'),note=str(b.get('note') or ''),restored_version=b.get('restored_version')); return j(p,200 if p.get('ok') else 404)
    @app.get('/api/learning/evaluations')
    def roadmap_learning_evaluations(): return jsonify({'ok':True,'status':'READY','evaluations':gov.evaluations(request.args.get('candidate_id'),int(request.args.get('limit',100)))})
    @app.get('/api/learning/shadow')
    def roadmap_learning_shadow(): return jsonify({'ok':True,'status':'SHADOW_ONLY' if gov.shadows() else 'COLLECTING','results':gov.shadows(request.args.get('candidate_id'),int(request.args.get('limit',100)))})
    @app.get('/api/learning/approvals')
    def roadmap_learning_approvals(): return jsonify({'ok':True,'status':'READY','approvals':gov.approvals(request.args.get('candidate_id'),int(request.args.get('limit',100)))})
    @app.get('/api/learning/rollbacks')
    def roadmap_learning_rollbacks(): return jsonify({'ok':True,'status':'READY','rollbacks':gov.rollbacks(int(request.args.get('limit',100)))})
    @app.get('/api/learning/audit')
    def roadmap_learning_audit(): return jsonify({'ok':True,'status':'READY','events':gov.audits(int(request.args.get('limit',100)))})
    @app.get('/api/learning/drift')
    def roadmap_learning_drift(): return jsonify({'ok':True,'status':'COLLECTING' if not gov.drift() else 'READY','events':gov.drift(int(request.args.get('limit',100)))})
    @app.post('/api/learning/drift')
    def roadmap_record_drift():
        b=request.get_json(silent=True) or {}; p=gov.record_drift(str(b.get('metric') or ''),str(b.get('severity') or ''),b.get('evidence') or {},production_version=b.get('production_version'),candidate_id=b.get('candidate_id'),status=str(b.get('status') or 'OPEN'),actor=str(b.get('actor') or 'API')); return j(p,201 if p.get('ok') else 400)

    # APEX 13.0 Sprint 7 governed offline weight optimization.
    @app.get('/api/learning/optimization/status')
    def optimization_status(): return jsonify({'ok':True,**weight_opt.status()})
    @app.post('/api/learning/optimization/run')
    def optimization_run():
        b=request.get_json(silent=True) or {}; p=weight_opt.run_optimization(actor=str(b.get('actor') or 'API'),step=float(b.get('step',0.1)),create_candidate=bool(b.get('create_candidate',True))); return j(p,201 if p.get('ok') else 409)
    @app.get('/api/learning/optimization/runs')
    def optimization_runs(): return jsonify({'ok':True,**weight_opt.status(),'runs':weight_opt.runs(int(request.args.get('limit',100)))})
    @app.post('/api/learning/candidates/<candidate_id>/shadow-scorecard')
    def optimization_shadow_scorecard(candidate_id):
        p=weight_opt.build_shadow_scorecard(candidate_id); return j(p,201 if p.get('ok') else 409)
    @app.get('/api/learning/shadow-scorecards')
    def optimization_shadow_scorecards(): return jsonify({'ok':True,'status':'READY','scorecards':weight_opt.shadow_scorecards(request.args.get('candidate_id'),int(request.args.get('limit',100)))})
    @app.get('/apex_os/offline_optimization')
    def offline_optimization_dashboard(): return render_template('offline_optimization.html')


    # APEX 13.0 Sprint 8 governed shadow validation.
    @app.get('/api/learning/shadow-campaigns')
    def shadow_campaigns_list(): return jsonify({'ok':True,'campaigns':shadow_validation.campaigns(int(request.args.get('limit',100)))})
    @app.post('/api/learning/shadow-campaigns')
    def shadow_campaigns_create():
        b=request.get_json(silent=True) or {}; p=shadow_validation.create_campaign(str(b.get('candidate_id') or ''),b,actor=str(b.get('actor') or 'API')); return j(p,201 if p.get('ok') else 409)
    @app.get('/api/learning/shadow-campaigns/<campaign_id>')
    def shadow_campaign_get(campaign_id):
        p=shadow_validation._campaign(campaign_id); return j({'ok':False,'status':'UNAVAILABLE','error':'not_found'},404) if not p else jsonify({'ok':True,**p})
    @app.post('/api/learning/shadow-campaigns/<campaign_id>/<action>')
    def shadow_campaign_action(campaign_id,action):
        if action not in {'start','pause','resume','terminate'}: return j({'ok':False,'status':'UNAVAILABLE','error':'invalid action'},404)
        b=request.get_json(silent=True) or {}; p=shadow_validation.transition(campaign_id,action,actor=str(b.get('actor') or 'API'),reason=str(b.get('reason') or '')); return j(p,200 if p.get('ok') else 409)
    @app.post('/api/learning/shadow-campaigns/<campaign_id>/observations')
    def shadow_campaign_observation(campaign_id):
        b=request.get_json(silent=True) or {}; p=shadow_validation.record_observation(campaign_id,b,actor=str(b.get('actor') or 'API')); return j(p,201 if p.get('ok') else 409)
    @app.get('/api/learning/shadow-campaigns/<campaign_id>/scorecard')
    def shadow_campaign_scorecard(campaign_id): return jsonify({'ok':True,**shadow_validation.scorecard(campaign_id)})
    @app.get('/api/learning/shadow-campaigns/<campaign_id>/coverage')
    def shadow_campaign_coverage(campaign_id): return jsonify({'ok':True,**shadow_validation.coverage(campaign_id)})
    @app.get('/api/learning/shadow-campaigns/<campaign_id>/gates')
    def shadow_campaign_gates(campaign_id): return jsonify({'ok':True,**shadow_validation.gate_results(campaign_id)})
    @app.post('/api/learning/shadow-campaigns/<campaign_id>/finalize')
    def shadow_campaign_finalize(campaign_id):
        b=request.get_json(silent=True) or {}; p=shadow_validation.finalize(campaign_id,actor=str(b.get('actor') or 'API')); return j(p,201 if p.get('ok') else 409)
    @app.get('/api/learning/promotion-packages')
    def promotion_packages(): return jsonify({'ok':True,'packages':shadow_validation.packages(int(request.args.get('limit',100)))})
    @app.get('/api/learning/champion-challenger')
    def champion_challenger(): return jsonify({'ok':True,**shadow_validation.champion_challenger(request.args.get('domain','decision_weights'))})
    @app.get('/apex_os/shadow_validation')
    def shadow_validation_dashboard(): return render_template('shadow_validation.html')


    # APEX 13.0 Sprint 9A production promotion governance.
    @app.get('/api/production/status')
    def production_governance_status(): return jsonify({'ok':True,**production_governance.status(request.args.get('domain','decision_weights'))})
    @app.get('/api/production/champion')
    def production_champion(): return jsonify({'ok':True,**shadow_validation.champion_challenger(request.args.get('domain','decision_weights'))})
    @app.get('/api/production/promotions')
    def production_promotions(): return jsonify({'ok':True,'promotions':production_governance.list_promotions(int(request.args.get('limit',100)))})
    @app.post('/api/production/promotions')
    def production_promotion_create():
        b=request.get_json(silent=True) or {}; p=production_governance.create_promotion(b,actor=str(b.get('actor') or 'API')); return j(p,201 if p.get('ok') else 409)
    @app.get('/api/production/promotions/<promotion_id>')
    def production_promotion_get(promotion_id):
        p=production_governance.promotion(promotion_id); return j({'ok':False,'status':'UNAVAILABLE','error':'not_found'},404) if not p else jsonify({'ok':True,**p,'approvals':production_governance.approvals(promotion_id)})
    @app.post('/api/production/promotions/<promotion_id>/approve')
    def production_promotion_approve(promotion_id):
        b=request.get_json(silent=True) or {}; p=production_governance.decide(promotion_id,b.get('role'), 'APPROVE',actor=str(b.get('actor') or 'API'),note=str(b.get('note') or ''),evidence=b.get('evidence')); return j(p,200 if p.get('ok') else 409)
    @app.post('/api/production/promotions/<promotion_id>/reject')
    def production_promotion_reject(promotion_id):
        b=request.get_json(silent=True) or {}; p=production_governance.decide(promotion_id,b.get('role'), 'REJECT',actor=str(b.get('actor') or 'API'),note=str(b.get('note') or ''),evidence=b.get('evidence')); return j(p,200 if p.get('ok') else 409)
    @app.post('/api/production/promotions/<promotion_id>/queue')
    def production_promotion_queue(promotion_id):
        b=request.get_json(silent=True) or {}; p=production_governance.queue(promotion_id,actor=str(b.get('actor') or 'API')); return j(p,201 if p.get('ok') else 409)
    @app.get('/api/production/manifests')
    def production_manifests(): return jsonify({'ok':True,'manifests':production_governance.manifests(int(request.args.get('limit',100)))})
    @app.get('/api/production/rollbacks')
    def production_rollbacks(): return jsonify({'ok':True,'rollback_targets':production_governance.rollback_targets(int(request.args.get('limit',100)))})
    @app.get('/api/production/audit')
    def production_audit(): return jsonify({'ok':True,'events':[x for x in gov.audits(int(request.args.get('limit',100))) if x.get('entity_type')=='production_promotion']})
    @app.get('/apex_os/production_governance')
    def production_governance_dashboard(): return render_template('production_governance.html')

    # APEX 13.0 Sprint 9B bounded canary deployment controller.
    @app.get('/api/production/canary/status')
    def canary_status(): return jsonify({'ok':True,**canary_deployment.status()})
    @app.get('/api/production/canaries')
    def canary_list(): return jsonify({'ok':True,'canaries':canary_deployment.list_canaries(int(request.args.get('limit',100)))})
    @app.post('/api/production/canaries')
    def canary_create():
        b=request.get_json(silent=True) or {}; p=canary_deployment.create(b,actor=str(b.get('actor') or 'API')); return j(p,201 if p.get('ok') else 409)
    @app.get('/api/production/canaries/<canary_id>')
    def canary_get(canary_id):
        p=canary_deployment.canary(canary_id); return j({'ok':False,'status':'UNAVAILABLE','error':'not_found'},404) if not p else jsonify({'ok':True,**p})
    @app.post('/api/production/canaries/<canary_id>/<action>')
    def canary_action(canary_id,action):
        if action not in {'start','pause','complete','stop'}: return j({'ok':False,'status':'UNAVAILABLE','error':'invalid action'},404)
        b=request.get_json(silent=True) or {}; p=canary_deployment.transition(canary_id,action,actor=str(b.get('actor') or 'API'),reason=str(b.get('reason') or '')); return j(p,200 if p.get('ok') else 409)
    @app.post('/api/production/canaries/<canary_id>/route')
    def canary_route(canary_id):
        b=request.get_json(silent=True) or {}; p=canary_deployment.route(canary_id,str(b.get('recommendation_id') or ''),b.get('context') or {}); return j(p,200 if p.get('ok') else 409)
    @app.post('/api/production/canaries/<canary_id>/health')
    def canary_health(canary_id):
        b=request.get_json(silent=True) or {}; p=canary_deployment.health(canary_id,b,actor=str(b.get('actor') or 'SYSTEM')); return j(p,200 if p.get('ok') else 409)
    @app.post('/api/production/canaries/<canary_id>/rollback')
    def canary_rollback(canary_id):
        b=request.get_json(silent=True) or {}; p=canary_deployment.rollback(canary_id,actor=str(b.get('actor') or 'API'),reason=str(b.get('reason') or 'manual rollback')); return j(p,200 if p.get('ok') else 409)
    @app.get('/api/production/canary-health')
    def canary_health_events(): return jsonify({'ok':True,'events':canary_deployment.events(request.args.get('canary_id'),int(request.args.get('limit',100)))})
    @app.get('/api/production/canary-rollbacks')
    def canary_rollbacks(): return jsonify({'ok':True,'rollbacks':canary_deployment.rollbacks(int(request.args.get('limit',100)))})
    @app.get('/apex_os/canary_deployment')
    def canary_dashboard(): return render_template('canary_deployment.html')

    # APEX 13.0 Sprint 9C institutional release manager.
    @app.get('/api/production/releases/status')
    def institutional_release_status(): return jsonify({'ok':True,**institutional_release_manager.status()})
    @app.get('/api/production/releases')
    def institutional_release_list(): return jsonify({'ok':True,'releases':institutional_release_manager.list_releases(int(request.args.get('limit',100)))})
    @app.post('/api/production/releases')
    def institutional_release_create():
        b=request.get_json(silent=True) or {}; p=institutional_release_manager.create(b,actor=str(b.get('actor') or 'API')); return j(p,201 if p.get('ok') else 409)
    @app.get('/api/production/releases/<release_id>')
    def institutional_release_get(release_id):
        p=institutional_release_manager.release(release_id); return j({'ok':False,'status':'UNAVAILABLE','error':'not_found'},404) if not p else jsonify({'ok':True,**p})
    @app.post('/api/production/releases/<release_id>/health')
    def institutional_release_health(release_id):
        b=request.get_json(silent=True) or {}; p=institutional_release_manager.capture_health(release_id,actor=str(b.get('actor') or 'SYSTEM')); return j(p,200 if p.get('ok') else 409)
    @app.post('/api/production/releases/<release_id>/close')
    def institutional_release_close(release_id):
        b=request.get_json(silent=True) or {}; p=institutional_release_manager.close(release_id,actor=str(b.get('actor') or 'API'),disposition=str(b.get('disposition') or 'CLOSED'),note=str(b.get('note') or '')); return j(p,200 if p.get('ok') else 409)
    @app.get('/api/production/releases/<release_id>/timeline')
    def institutional_release_timeline(release_id): return jsonify({'ok':True,'events':institutional_release_manager.timeline(release_id,int(request.args.get('limit',100)))})
    @app.get('/api/production/release-health')
    def institutional_release_health_list(): return jsonify({'ok':True,'snapshots':institutional_release_manager.health_snapshots(request.args.get('release_id'),int(request.args.get('limit',100)))})
    @app.get('/apex_os/release_manager')
    def institutional_release_dashboard(): return render_template('institutional_release_manager.html')

    # APEX 13.0 Sprint 1 institutional evidence case files.
    @app.get('/api/evidence/status')
    def evidence_status(): return jsonify({'ok':True,**evidence.status()})
    @app.post('/api/evidence/<recommendation_id>/capture')
    def evidence_capture(recommendation_id):
        p=evidence.capture(recommendation_id); return j(p,201 if p.get('created') else (200 if p.get('ok') else 404))
    @app.get('/api/evidence/<recommendation_id>')
    def evidence_get(recommendation_id):
        p=evidence.get(recommendation_id); return j({'ok':False,'status':'UNAVAILABLE','error':'not_found'},404) if p is None else jsonify({'ok':True,**p})
    @app.get('/api/evidence/<recommendation_id>/timeline')
    def evidence_timeline(recommendation_id): return jsonify({'ok':True,'recommendation_id':recommendation_id,'events':evidence.timeline(recommendation_id)})
    @app.get('/api/evidence/<recommendation_id>/integrity')
    def evidence_integrity(recommendation_id):
        p=evidence.validate(recommendation_id); return j(p,200 if p.get('status')!='UNAVAILABLE' else 404)
    @app.get('/api/evidence/<recommendation_id>/metadata')
    def evidence_metadata(recommendation_id):
        p=evidence.metadata(recommendation_id); return j({'ok':False,'status':'UNAVAILABLE','error':'not_found'},404) if p is None else jsonify({'ok':True,**p})
    @app.get('/apex_os/evidence/<recommendation_id>')
    def evidence_case_file(recommendation_id): return render_template('institutional_case_file.html',recommendation_id=recommendation_id)

    # APEX 13.0 Sprint 2 institutional data-quality framework.
    @app.get('/api/data-quality/status')
    @app.get('/api/data-quality/report')
    def data_quality_status(): return jsonify({'ok':True,**data_quality.report()})
    @app.post('/api/data-quality/assess-all')
    def data_quality_assess_all(): return jsonify(data_quality.assess_all(int((request.get_json(silent=True) or {}).get('limit',500))))
    @app.get('/api/data-quality/<recommendation_id>')
    def data_quality_get(recommendation_id):
        p=data_quality.latest(recommendation_id) or data_quality.assess(recommendation_id)
        return j(p,200 if p.get('status')!='UNAVAILABLE' else 404)
    @app.post('/api/data-quality/<recommendation_id>/assess')
    def data_quality_assess(recommendation_id):
        p=data_quality.assess(recommendation_id); return j(p,200 if p.get('status')!='UNAVAILABLE' else 404)
    @app.get('/apex_os/data_quality')
    def data_quality_dashboard(): return render_template('data_quality_dashboard.html')

    # APEX 13.0 Sprint 3 historical readiness and evidence coverage.
    @app.get('/api/historical-readiness/status')
    def historical_readiness_status(): return jsonify({'ok':True,**historical_readiness.status()})
    @app.get('/api/historical-readiness/report')
    @app.get('/api/historical-readiness/coverage')
    @app.get('/api/historical-readiness/gates')
    def historical_readiness_report(): return jsonify({'ok':True,**historical_readiness.build_report()})
    @app.get('/apex_os/historical_readiness')
    def historical_readiness_dashboard(): return render_template('historical_readiness_dashboard.html')

    # APEX 13.0 Sprint 4 evidence-backed similarity intelligence.
    @app.get('/api/research/vector')
    def institutional_vector_create():
        rid=request.args.get('recommendation_id','').strip()
        if not rid: return j({'ok':False,'status':'UNAVAILABLE','error':'recommendation_id required'},400)
        p=institutional_similarity.create_vector(rid); return j(p,200 if p.get('ok') else 404)
    @app.post('/api/research/vector/<recommendation_id>')
    def institutional_vector_capture(recommendation_id):
        p=institutional_similarity.create_vector(recommendation_id); return j(p,201 if p.get('created') else (200 if p.get('ok') else 404))
    @app.get('/api/research/vector/<identifier>')
    def institutional_vector_get(identifier):
        p=institutional_similarity.get_vector(identifier); return j({'ok':False,'status':'UNAVAILABLE','error':'not_found'},404) if p is None else jsonify({'ok':True,'status':'READY',**p})
    @app.post('/api/research/vectors/build')
    def institutional_vectors_build(): return jsonify(institutional_similarity.create_all(int((request.get_json(silent=True) or {}).get('limit',500))))
    @app.get('/api/research/features')
    @app.get('/api/research/schema')
    def institutional_similarity_schema(): return jsonify({'ok':True,**institutional_similarity.schema()})
    @app.get('/api/research/institutional-similarity/<identifier>')
    def institutional_similarity_search(identifier): return jsonify({'ok':True,**institutional_similarity.search(identifier,top_k=int(request.args.get('top_k',10)),as_of=request.args.get('as_of'))})
    @app.get('/api/research/institutional-status')
    def institutional_similarity_status(): return jsonify({'ok':True,**institutional_similarity.status()})

    @app.get('/apex_os/institutional_research')
    def roadmap_research_dashboard(): return render_template('institutional_research.html')
    @app.get('/apex_os/strategy_intelligence')
    def strategy_intelligence_dashboard(): return render_template('strategy_intelligence.html')
    @app.get('/apex_os/institutional_similarity')
    def institutional_similarity_dashboard(): return render_template('institutional_similarity_lab.html')
    @app.get('/apex_os/adaptive_learning')
    def roadmap_learning_dashboard(): return render_template('adaptive_learning.html')

    # APEX 14 Sprint 10.1 — immutable Decision Intelligence Core.
    @app.get('/api/decision-intelligence/status')
    def decision_intelligence_status(): return jsonify({'ok':True,**decision_intelligence_core.status()})
    @app.get('/api/decision-intelligence/records')
    def decision_intelligence_records(): return jsonify({'ok':True,'status':'READY','records':decision_intelligence_core.list_records(int(request.args.get('limit',100)))})
    @app.post('/api/decision-intelligence/capture')
    def decision_intelligence_capture():
        b=request.get_json(silent=True) or {}; rid=str(b.get('recommendation_id') or '').strip()
        payload=b.get('decision_source') if isinstance(b.get('decision_source'),dict) else current()
        out=decision_intelligence_core.capture(payload,recommendation_id=rid,actor=str(b.get('actor') or 'API'),session_state=b.get('session_state'))
        return j(out,201 if out.get('created') else (200 if out.get('ok') else 409))
    @app.get('/api/decision-intelligence/<identifier>')
    def decision_intelligence_record(identifier):
        out=decision_intelligence_core.get(identifier)
        return j({'ok':False,'status':'UNAVAILABLE','error':'not_found'},404) if out is None else jsonify({'ok':True,'record':out})
    @app.get('/api/decision-intelligence/<identifier>/evidence')
    def decision_intelligence_evidence(identifier):
        out=decision_intelligence_core.get(identifier)
        return j({'ok':False,'status':'UNAVAILABLE','error':'not_found'},404) if out is None else jsonify({'ok':True,'status':'READY','decision_id':out['decision_id'],'evidence':out['evidence']})
    @app.get('/api/decision-intelligence/<identifier>/contributions')
    def decision_intelligence_contributions(identifier):
        out=decision_intelligence_core.get(identifier)
        return j({'ok':False,'status':'UNAVAILABLE','error':'not_found'},404) if out is None else jsonify({'ok':True,'status':'READY','decision_id':out['decision_id'],'contributions':out['contributions']})
    @app.get('/api/decision-intelligence/<identifier>/timeline')
    def decision_intelligence_timeline(identifier):
        out=decision_intelligence_core.get(identifier)
        return j({'ok':False,'status':'UNAVAILABLE','error':'not_found'},404) if out is None else jsonify({'ok':True,'status':'READY','decision_id':out['decision_id'],'timeline':out['timeline']})
    # APEX 14 Sprint 10.2 — deterministic Confidence Attribution Engine.
    @app.get('/api/decision-intelligence/confidence/status')
    def confidence_attribution_status(): return jsonify({'ok':True,**confidence_attribution_engine.status()})
    @app.get('/api/decision-intelligence/confidence/analyses')
    def confidence_attribution_analyses(): return jsonify({'ok':True,'status':'READY','analyses':confidence_attribution_engine.list_analyses(int(request.args.get('limit',100)))})
    @app.post('/api/decision-intelligence/<identifier>/confidence/analyze')
    def confidence_attribution_analyze(identifier):
        b=request.get_json(silent=True) or {}; out=confidence_attribution_engine.analyze(identifier,actor=str(b.get('actor') or 'API'))
        return j(out,201 if out.get('created') else (200 if out.get('ok') else 404))
    @app.get('/api/decision-intelligence/<identifier>/confidence')
    def confidence_attribution_explain(identifier):
        out=confidence_attribution_engine.explain(identifier)
        return j(out,200 if out.get('ok') else 404)
    @app.get('/apex_os/confidence_attribution')
    def confidence_attribution_dashboard(): return render_template('confidence_attribution.html')

    # APEX 14 Sprint 10.3 — immutable Institutional Evidence Graph.
    @app.get('/api/decision-intelligence/graph/status')
    def evidence_graph_status(): return jsonify({'ok':True,**institutional_evidence_graph.status()})
    @app.get('/api/decision-intelligence/graphs')
    def evidence_graphs(): return jsonify({'ok':True,'status':'READY','graphs':institutional_evidence_graph.list_graphs(int(request.args.get('limit',100)))})
    @app.post('/api/decision-intelligence/<identifier>/graph/build')
    def evidence_graph_build(identifier):
        b=request.get_json(silent=True) or {}; out=institutional_evidence_graph.create(identifier,actor=str(b.get('actor') or 'API'))
        return j(out,201 if out.get('created') else (200 if out.get('ok') else 404))
    @app.get('/api/decision-intelligence/<identifier>/graph')
    def evidence_graph_get(identifier):
        out=institutional_evidence_graph.explain(identifier); return j(out,200 if out.get('ok') else 404)
    @app.get('/apex_os/evidence_graph')
    def evidence_graph_dashboard(): return render_template('institutional_evidence_graph.html')

    # APEX 14 Sprint 10.4 — unified Decision Intelligence Center.
    @app.get('/api/dic/status')
    def dic_status(): return jsonify({'ok':True,**decision_intelligence_center.status()})
    @app.get('/api/dic/summary/<identifier>')
    def dic_summary(identifier):
        out=decision_intelligence_center.summary(identifier); return j(out,200 if out.get('ok') else 404)
    @app.get('/api/dic/dashboard/<identifier>')
    def dic_dashboard(identifier):
        out=decision_intelligence_center.dashboard(identifier); return j(out,200 if out.get('ok') else 404)
    @app.get('/api/dic/evidence/<identifier>')
    def dic_evidence(identifier):
        out=decision_intelligence_center.dashboard(identifier); return j({'ok':False,'status':'UNAVAILABLE'},404) if not out.get('ok') else jsonify({'ok':True,'supporting_evidence':out['supporting_evidence'],'conflicting_evidence':out['conflicting_evidence']})
    @app.get('/api/dic/confidence/<identifier>')
    def dic_confidence(identifier):
        out=decision_intelligence_center.dashboard(identifier); return j({'ok':False,'status':'UNAVAILABLE'},404) if not out.get('ok') else jsonify({'ok':True,'confidence':out['confidence']})
    @app.get('/api/dic/timeline/<identifier>')
    def dic_timeline(identifier):
        out=decision_intelligence_center.dashboard(identifier); return j({'ok':False,'status':'UNAVAILABLE'},404) if not out.get('ok') else jsonify({'ok':True,'timeline':out['timeline']})
    @app.get('/api/dic/risk/<identifier>')
    def dic_risk(identifier):
        out=decision_intelligence_center.dashboard(identifier); return j({'ok':False,'status':'UNAVAILABLE'},404) if not out.get('ok') else jsonify({'ok':True,'risk':out['risk'],'invalidation':out['invalidation']})
    @app.get('/api/dic/governance/<identifier>')
    def dic_governance(identifier):
        out=decision_intelligence_center.dashboard(identifier); return j({'ok':False,'status':'UNAVAILABLE'},404) if not out.get('ok') else jsonify({'ok':True,'governance':out['governance']})
    @app.get('/apex_os/decision_intelligence_center')
    def dic_dashboard_page(): return render_template('decision_intelligence_center.html')

    # APEX 14 Sprint 10.5 — Institutional Replay 2.0.
    @app.get('/api/replay2/status')
    def replay2_status(): return jsonify({'ok':True,**institutional_replay_2.status()})
    @app.get('/api/replay2/replays')
    def replay2_list(): return jsonify({'ok':True,'status':'READY','replays':institutional_replay_2.list_replays(int(request.args.get('limit',100)))})
    @app.post('/api/replay2/<identifier>/build')
    def replay2_build(identifier):
        b=request.get_json(silent=True) or {}; out=institutional_replay_2.create(identifier,actor=str(b.get('actor') or 'API'))
        return j(out,201 if out.get('created') else (200 if out.get('ok') else 404))
    @app.get('/api/replay2/<identifier>')
    def replay2_get(identifier):
        out=institutional_replay_2.get(identifier); return j(out,200 if out.get('ok') else 404)
    @app.get('/api/replay2/<identifier>/frames')
    def replay2_frames(identifier):
        out=institutional_replay_2.get(identifier); return j(out,404) if not out.get('ok') else jsonify({'ok':True,'decision_id':out['decision_id'],'frames':out['replay']['frames']})
    @app.get('/apex_os/institutional_replay')
    def replay2_dashboard(): return render_template('institutional_replay_2.html')

    # Sprint 10.6 — Institutional Cross-Examination Engine.
    @app.get('/api/cross-examination/status')
    def cross_exam_status(): return jsonify({'ok':True,**cross_examination_engine.status()})
    @app.get('/api/cross-examination/questions')
    def cross_exam_questions(): return jsonify({'ok':True,'status':'READY','questions':cross_examination_engine.questions()})
    @app.post('/api/cross-examination/ask')
    def cross_exam_ask():
        b=request.get_json(silent=True) or {}; identifier=str(b.get('identifier') or b.get('decision_id') or '')
        out=cross_examination_engine.ask(identifier,str(b.get('question') or ''),actor=str(b.get('actor') or 'API'))
        return j(out,200 if out.get('ok') else 400 if out.get('status')=='INVALID_REQUEST' else 404)
    @app.get('/api/cross-examination/history')
    def cross_exam_history_all(): return jsonify({'ok':True,'status':'READY','history':cross_examination_engine.history(limit=int(request.args.get('limit',100)))})
    @app.get('/api/cross-examination/history/<identifier>')
    def cross_exam_history(identifier): return jsonify({'ok':True,'status':'READY','history':cross_examination_engine.history(identifier,int(request.args.get('limit',100)))})
    @app.get('/api/cross-examination/explain/<identifier>')
    def cross_exam_explain(identifier):
        out=cross_examination_engine.ask(identifier,str(request.args.get('question') or 'Why did APEX recommend this?'),actor='API',persist=False)
        return j(out,200 if out.get('ok') else 404)
    @app.get('/api/cross-examination/compare/<identifier_a>/<identifier_b>')
    def cross_exam_compare(identifier_a,identifier_b):
        out=cross_examination_engine.compare(identifier_a,identifier_b); return j(out,200 if out.get('ok') else 404)
    @app.get('/apex_os/cross_examination')
    def cross_exam_dashboard(): return render_template('cross_examination.html')


    # APEX 15.1 — Institutional Market State Engine (IMSE).
    @app.get('/api/imse/status')
    def imse_status(): return jsonify({'ok':True,**imse.status()})
    @app.post('/api/imse/classify')
    def imse_classify():
        b=request.get_json(silent=True) or {}; snapshot=b.get('snapshot') if isinstance(b.get('snapshot'),dict) else b
        return jsonify({'ok':True,'status':'CLASSIFIED',**imse.classify(snapshot)})
    @app.post('/api/imse/record')
    def imse_record():
        b=request.get_json(silent=True) or {}; snapshot=b.get('snapshot') if isinstance(b.get('snapshot'),dict) else b
        out=imse.record(snapshot,symbol=str(b.get('symbol') or 'SPX'),session_id=str(b.get('session_id') or ''),observed_at=b.get('observed_at'),actor=str(b.get('actor') or 'API'))
        return j(out,201 if out.get('created') else 200)
    @app.get('/api/imse/current')
    def imse_current():
        out=imse.current(str(request.args.get('symbol') or 'SPX')); return j(out,200 if out.get('ok') else 404)
    @app.get('/api/imse/history')
    def imse_history(): return jsonify({'ok':True,'status':'READY','history':imse.history(str(request.args.get('symbol') or 'SPX'),int(request.args.get('limit',100)))})
    @app.get('/api/imse/transitions')
    def imse_transitions(): return jsonify({'ok':True,'status':'READY','transitions':imse.transitions(str(request.args.get('symbol') or 'SPX'),int(request.args.get('limit',100)))})
    @app.get('/api/imse/dashboard')
    def imse_dashboard_api(): return jsonify(imse.dashboard(str(request.args.get('symbol') or 'SPX')))
    @app.get('/apex_os/regime_intelligence')
    @app.get('/apex_os/institutional_market_state')
    def imse_dashboard_page(): return render_template('institutional_market_state.html')


    # APEX 15.2 — Institutional Playbook Engine (IPE).
    @app.get('/api/playbooks/status')
    def ipe_status(): return jsonify({'ok':True,**ipe.status()})
    @app.get('/api/playbooks/library')
    def ipe_library(): return jsonify({'ok':True,'status':'READY','library':[{'playbook_id':x['id'],'name':x['name'],'family':x['family'],'compatible_states':x['states'],'invalidation':x['invalidation']} for x in ipe.PLAYBOOK_LIBRARY]})
    @app.post('/api/playbooks/evaluate')
    def ipe_evaluate():
        b=request.get_json(silent=True) or {}; snapshot=b.get('snapshot') if isinstance(b.get('snapshot'),dict) else b
        return jsonify({'ok':True,'status':'EVALUATED',**ipe.evaluate(snapshot,symbol=str(b.get('symbol') or 'SPX'),observed_at=b.get('observed_at'))})
    @app.post('/api/playbooks/record')
    def ipe_record():
        b=request.get_json(silent=True) or {}; snapshot=b.get('snapshot') if isinstance(b.get('snapshot'),dict) else b
        out=ipe.record(snapshot,symbol=str(b.get('symbol') or 'SPX'),session_id=str(b.get('session_id') or ''),observed_at=b.get('observed_at'),actor=str(b.get('actor') or 'API'))
        return j(out,201 if out.get('created') else 200)
    @app.get('/api/playbooks/current')
    def ipe_current():
        out=ipe.current(str(request.args.get('symbol') or 'SPX')); return j(out,200 if out.get('ok') else 404)
    @app.get('/api/playbooks/history')
    def ipe_history(): return jsonify({'ok':True,'status':'READY','history':ipe.history(str(request.args.get('symbol') or 'SPX'),int(request.args.get('limit',100)))})
    @app.get('/api/playbooks/transitions')
    def ipe_transitions(): return jsonify({'ok':True,'status':'READY','transitions':ipe.transitions(str(request.args.get('symbol') or 'SPX'),int(request.args.get('limit',100)))})
    @app.get('/api/playbooks/statistics')
    def ipe_statistics(): return jsonify(ipe.statistics(request.args.get('playbook_id')))
    @app.get('/api/playbooks/dashboard')
    def ipe_dashboard_api(): return jsonify(ipe.dashboard(str(request.args.get('symbol') or 'SPX')))
    @app.get('/apex_os/playbook_engine')
    @app.get('/apex_os/institutional_playbooks')
    def ipe_dashboard_page(): return render_template('institutional_playbook_engine.html')

    # APEX 15.3 — Prediction and Confidence Calibration Engine.
    @app.get('/api/calibration/status')
    def pcce_status(): return jsonify({'ok':True,**pcce.status()})
    @app.post('/api/calibration/observations')
    def pcce_ingest():
        b=request.get_json(silent=True) or {}; out=pcce.ingest(str(b.get('prediction_id') or ''),float(b.get('confidence') or 0),b.get('outcome',False),symbol=str(b.get('symbol') or 'SPX'),predicted_at=str(b.get('predicted_at') or ''),outcome_at=str(b.get('outcome_at') or ''),segment=b.get('segment') or {},source=b.get('source') or {},actor=str(b.get('actor') or 'API')); return j(out,201 if out.get('created') else 200)
    @app.post('/api/calibration/analyze')
    def pcce_analyze():
        b=request.get_json(silent=True) or {}; return jsonify(pcce.analyze(as_of=b.get('as_of'),symbol=b.get('symbol'),bin_width=int(b.get('bin_width') or 10),persist=bool(b.get('persist',True)),actor=str(b.get('actor') or 'API')))
    @app.get('/api/calibration/analyses')
    def pcce_analyses(): return jsonify({'ok':True,'status':'READY','analyses':pcce.analyses(int(request.args.get('limit',100)))})
    @app.get('/api/calibration/dashboard')
    def pcce_dashboard_api(): return jsonify(pcce.dashboard(request.args.get('symbol')))
    @app.get('/apex_os/confidence_calibration')
    @app.get('/apex_os/prediction_calibration')
    def pcce_dashboard_page(): return render_template('prediction_confidence_calibration.html')

    # APEX 15.4 — Institutional Execution Intelligence.
    @app.get('/api/execution-intelligence/status')
    def iei_status(): return jsonify({'ok':True,**iei.status()})
    @app.post('/api/execution-intelligence/evaluate')
    def iei_evaluate():
        b=request.get_json(silent=True) or {}; return jsonify({'ok':True,'status':'EVALUATED',**iei.evaluate_trade(side=str(b.get('side') or 'LONG'),quantity=float(b.get('quantity') or 1),planned_entry=float(b.get('planned_entry') or 0),actual_entry=float(b.get('actual_entry') or 0),actual_exit=float(b.get('actual_exit') or 0),opened_at=str(b.get('opened_at') or ''),closed_at=str(b.get('closed_at') or ''),stop_price=b.get('stop_price'),best_price=b.get('best_price'),worst_price=b.get('worst_price'),fees=float(b.get('fees') or 0),context=b.get('context') or {})})
    @app.post('/api/execution-intelligence/records')
    def iei_record():
        b=request.get_json(silent=True) or {}; out=iei.record(trade_id=str(b.get('trade_id') or ''),symbol=str(b.get('symbol') or 'SPX'),side=str(b.get('side') or 'LONG'),quantity=float(b.get('quantity') or 1),planned_entry=float(b.get('planned_entry') or 0),actual_entry=float(b.get('actual_entry') or 0),actual_exit=float(b.get('actual_exit') or 0),opened_at=str(b.get('opened_at') or ''),closed_at=str(b.get('closed_at') or ''),stop_price=b.get('stop_price'),best_price=b.get('best_price'),worst_price=b.get('worst_price'),fees=float(b.get('fees') or 0),context=b.get('context') or {},actor=str(b.get('actor') or 'API')); return j(out,201 if out.get('created') else 200)
    @app.get('/api/execution-intelligence/records')
    def iei_records(): return jsonify({'ok':True,'status':'READY','records':iei.records(int(request.args.get('limit',100)),request.args.get('symbol'))})
    @app.post('/api/execution-intelligence/analyze')
    def iei_analyze():
        b=request.get_json(silent=True) or {}; return jsonify(iei.analyze(symbol=b.get('symbol'),as_of=b.get('as_of'),persist=bool(b.get('persist',True)),actor=str(b.get('actor') or 'API')))
    @app.get('/api/execution-intelligence/dashboard')
    def iei_dashboard_api(): return jsonify(iei.dashboard(request.args.get('symbol')))
    @app.get('/apex_os/execution_intelligence')
    @app.get('/apex_os/institutional_execution_intelligence')
    def iei_dashboard_page(): return render_template('institutional_execution_intelligence.html')

    # APEX 15.5 — Institutional Research Lab and Alpha Attribution.
    @app.get('/api/research-lab/status')
    def irl_status(): return jsonify({'ok':True,**irl.status()})
    @app.post('/api/research-lab/candidates')
    def irl_candidate():
        b=request.get_json(silent=True) or {}; out=irl.register_candidate(name=str(b.get('name') or ''),candidate_type=str(b.get('candidate_type') or 'STRATEGY'),hypothesis=str(b.get('hypothesis') or ''),specification=b.get('specification') or {},owner=str(b.get('owner') or 'SYSTEM'),actor=str(b.get('actor') or 'API')); return j(out,201 if out.get('created') else 200)
    @app.get('/api/research-lab/candidates')
    def irl_candidates(): return jsonify({'ok':True,'status':'READY','candidates':irl.candidates(int(request.args.get('limit',100)))})
    @app.post('/api/research-lab/runs')
    def irl_run():
        b=request.get_json(silent=True) or {}; out=irl.record_run(candidate_id=str(b.get('candidate_id') or ''),dataset_id=str(b.get('dataset_id') or ''),started_at=str(b.get('started_at') or ''),completed_at=str(b.get('completed_at') or ''),methodology=b.get('methodology') or {},metrics=b.get('metrics') or {},diagnostics=b.get('diagnostics') or {},actor=str(b.get('actor') or 'API')); return j(out,201 if out.get('created') else 200)
    @app.get('/api/research-lab/runs')
    def irl_runs(): return jsonify({'ok':True,'status':'READY','runs':irl.runs(request.args.get('candidate_id'),int(request.args.get('limit',100)))})
    @app.post('/api/research-lab/compare')
    def irl_compare():
        b=request.get_json(silent=True) or {}; return jsonify(irl.compare(list(b.get('candidate_ids') or [])))
    @app.post('/api/research-lab/readiness')
    def irl_readiness():
        b=request.get_json(silent=True) or {}; return jsonify(irl.assess_readiness(str(b.get('candidate_id') or ''),persist=bool(b.get('persist',True)),actor=str(b.get('actor') or 'API')))
    @app.post('/api/alpha-attribution/records')
    def irl_attribution():
        b=request.get_json(silent=True) or {}; out=irl.alpha_attribution(scope_id=str(b.get('scope_id') or ''),total_result=float(b.get('total_result') or 0),contributions=b.get('contributions') or {},observed_at=b.get('observed_at'),actor=str(b.get('actor') or 'API')); return j(out,201 if out.get('created') else 200)
    @app.get('/api/alpha-attribution/records')
    def irl_attributions(): return jsonify({'ok':True,'status':'READY','records':irl.attributions(int(request.args.get('limit',100)))})
    @app.get('/api/research-lab/dashboard')
    def irl_dashboard_api(): return jsonify(irl.dashboard())
    @app.get('/apex_os/research_lab')
    @app.get('/apex_os/alpha_attribution')
    def irl_dashboard_page(): return render_template('institutional_research_lab.html')

    # APEX 16.0 — Institutional Trading Desk / Order Flow Intelligence 2.0.
    @app.get('/api/order-flow-intelligence/status')
    def iofi_status(): return jsonify({'ok':True,**iofi.status()})
    @app.post('/api/order-flow-intelligence/evaluate')
    def iofi_evaluate():
        b=request.get_json(silent=True) or {}; snapshot=b.get('snapshot') if isinstance(b.get('snapshot'),dict) else b
        return jsonify({'ok':True,'status':'EVALUATED',**iofi.evaluate(snapshot)})
    @app.post('/api/order-flow-intelligence/record')
    def iofi_record():
        b=request.get_json(silent=True) or {}; snapshot=b.get('snapshot') if isinstance(b.get('snapshot'),dict) else b
        out=iofi.record(snapshot,symbol=str(b.get('symbol') or 'SPX'),session_id=str(b.get('session_id') or ''),observed_at=b.get('observed_at'),actor=str(b.get('actor') or 'API'))
        return j(out,201 if out.get('created') else 200)
    @app.get('/api/order-flow-intelligence/current')
    def iofi_current():
        out=iofi.current(str(request.args.get('symbol') or 'SPX'),request.args.get('as_of')); return j(out,200 if out.get('ok') else 404)
    @app.get('/api/order-flow-intelligence/history')
    def iofi_history(): return jsonify({'ok':True,'status':'READY','history':iofi.history(str(request.args.get('symbol') or 'SPX'),int(request.args.get('limit',100)))})
    @app.get('/api/order-flow-intelligence/transitions')
    def iofi_transitions(): return jsonify({'ok':True,'status':'READY','transitions':iofi.transitions(str(request.args.get('symbol') or 'SPX'),int(request.args.get('limit',100)))})
    @app.get('/api/order-flow-intelligence/dashboard')
    def iofi_dashboard(): return jsonify(iofi.dashboard(str(request.args.get('symbol') or 'SPX')))
    @app.get('/api/trading-desk/status')
    @app.get('/api/mission-control/status')
    def trading_desk_status(): return jsonify({'ok':True,**lmc.status(),'centerpiece':'INSTITUTIONAL_ORDER_FLOW_INTELLIGENCE_2'})
    @app.get('/api/trading-desk/dashboard')
    @app.get('/api/mission-control/dashboard')
    def trading_desk_dashboard():
        symbol=str(request.args.get('symbol') or 'SPX')
        return jsonify(lmc.dashboard(symbol,current()))
    @app.post('/api/mission-control/confluence')
    def mission_control_confluence():
        b=request.get_json(silent=True) or {}
        return jsonify({'ok':True,'status':'EVALUATED',**lmc.confluence(pressure=b.get('pressure'),market_state=b.get('market_state'),playbook=b.get('playbook'),engine_snapshot=b.get('engine_snapshot'))})

    # APEX 16.2 — Adaptive Trade Management (advisory only).
    @app.get('/api/trade-management/status')
    def adaptive_trade_management_status(): return jsonify({'ok':True,**atm.status()})
    @app.post('/api/trade-management/evaluate')
    def adaptive_trade_management_evaluate():
        b=request.get_json(silent=True) or {}; snapshot=b.get('snapshot') if isinstance(b.get('snapshot'),dict) else b
        return jsonify({'ok':True,**atm.evaluate(snapshot)})
    @app.post('/api/trade-management/record')
    def adaptive_trade_management_record():
        b=request.get_json(silent=True) or {}; snapshot=b.get('snapshot') if isinstance(b.get('snapshot'),dict) else b
        out=atm.record(snapshot,trade_id=b.get('trade_id'),symbol=str(b.get('symbol') or 'SPX'),observed_at=b.get('observed_at'),actor=str(b.get('actor') or 'API'))
        return j(out,201 if out.get('created') else 200)
    @app.get('/api/trade-management/history')
    def adaptive_trade_management_history():
        return jsonify({'ok':True,'status':'READY','history':atm.history(request.args.get('trade_id'),int(request.args.get('limit',100)))})
    # APEX 16.3 — Portfolio & Risk Intelligence (advisory only).
    @app.get('/api/portfolio-risk/status')
    def portfolio_risk_status(): return jsonify({'ok':True,**pri.status()})
    @app.post('/api/portfolio-risk/evaluate')
    def portfolio_risk_evaluate():
        b=request.get_json(silent=True) or {}; snapshot=b.get('snapshot') if isinstance(b.get('snapshot'),dict) else b
        return jsonify({'ok':True,**pri.evaluate(snapshot)})
    @app.post('/api/portfolio-risk/record')
    def portfolio_risk_record():
        b=request.get_json(silent=True) or {}; snapshot=b.get('snapshot') if isinstance(b.get('snapshot'),dict) else b
        out=pri.record(snapshot,account_id=str(b.get('account_id') or 'PRIMARY'),observed_at=b.get('observed_at'),actor=str(b.get('actor') or 'API'))
        return j(out,201 if out.get('created') else 200)
    @app.get('/api/portfolio-risk/history')
    def portfolio_risk_history(): return jsonify({'ok':True,'status':'READY','history':pri.history(str(request.args.get('account_id') or 'PRIMARY'),int(request.args.get('limit',100)))})

    # APEX 16.4 — Explainable Intelligence Assistant.
    @app.get('/api/explainable-intelligence/status')
    def explainable_intelligence_status(): return jsonify({'ok':True,**eia.status()})
    @app.post('/api/explainable-intelligence/ask')
    def explainable_intelligence_ask():
        b=request.get_json(silent=True) or {}; snapshot=b.get('snapshot') if isinstance(b.get('snapshot'),dict) else lmc.dashboard(str(b.get('symbol') or 'SPX'),current())
        return jsonify({'ok':True,**eia.explain(str(b.get('question') or ''),snapshot,b.get('previous_snapshot'),b.get('similar_sessions'))})
    @app.post('/api/explainable-intelligence/record')
    def explainable_intelligence_record():
        b=request.get_json(silent=True) or {}; snapshot=b.get('snapshot') if isinstance(b.get('snapshot'),dict) else lmc.dashboard(str(b.get('symbol') or 'SPX'),current())
        out=eia.record(str(b.get('question') or ''),snapshot,symbol=str(b.get('symbol') or 'SPX'),observed_at=b.get('observed_at'),previous_snapshot=b.get('previous_snapshot'),similar_sessions=b.get('similar_sessions'),actor=str(b.get('actor') or 'API'))
        return j(out,201 if out.get('created') else 200)
    @app.get('/api/explainable-intelligence/history')
    def explainable_intelligence_history(): return jsonify({'ok':True,'status':'READY','history':eia.history(str(request.args.get('symbol') or 'SPX'),int(request.args.get('limit',100)))})

    # APEX 16.5 — Performance Intelligence (descriptive completed-outcome coaching).
    @app.get('/api/performance-intelligence/status')
    def performance_intelligence_status(): return jsonify({'ok':True,**pi.status()})
    @app.post('/api/performance-intelligence/evaluate')
    def performance_intelligence_evaluate():
        b=request.get_json(silent=True) or {}; trades=b.get('trades') if isinstance(b.get('trades'),list) else []
        return jsonify({'ok':True,**pi.analyze(trades,symbol=str(b.get('symbol') or 'SPX'),minimum_sample=int(b.get('minimum_sample',3)))})
    @app.post('/api/performance-intelligence/observations')
    def performance_intelligence_observation():
        b=request.get_json(silent=True) or {}; trade=b.get('trade') if isinstance(b.get('trade'),dict) else b
        out=pi.record_observation(trade,actor=str(b.get('actor') or 'API')); return j(out,201 if out.get('created') else 200)
    @app.post('/api/performance-intelligence/analyze')
    def performance_intelligence_analyze():
        b=request.get_json(silent=True) or {}; return jsonify({'ok':True,**pi.analyze_stored(str(b.get('symbol') or 'SPX'),persist=bool(b.get('persist')),actor=str(b.get('actor') or 'API'))})
    @app.get('/api/performance-intelligence/dashboard')
    def performance_intelligence_dashboard(): return jsonify(pi.dashboard(str(request.args.get('symbol') or 'SPX')))


    # APEX 16.6 — Live Operations & Data Integrity Command.
    @app.get('/api/live-operations/status')
    def live_operations_status(): return jsonify({'ok':True,**lo.status()})
    @app.get('/api/live-operations/sources')
    def live_operations_sources():
        x=lo.latest(str(request.args.get('symbol') or 'SPX')); return jsonify({'ok':True,'status':'READY','sources':x.get('sources',[])})
    @app.post('/api/live-operations/evaluate')
    def live_operations_evaluate(): return jsonify({'ok':True,**lo.evaluate(request.get_json(silent=True) or {})})
    @app.post('/api/live-operations/record')
    def live_operations_record():
        out=lo.record_assessment(request.get_json(silent=True) or {},actor=str((request.get_json(silent=True) or {}).get('actor') or 'API')); return j(out,201 if out.get('created') else 200)
    @app.get('/api/live-operations/incidents')
    def live_operations_incidents(): return jsonify({'ok':True,'status':'READY','incidents':lo.incidents(int(request.args.get('limit',100)))})
    @app.get('/api/live-operations/session')
    def live_operations_session(): return jsonify({'ok':True,'status':'READY','session':lo.session_state(request.args.get('at'))})
    @app.get('/api/live-operations/tradeability')
    def live_operations_tradeability():
        x=lo.latest(str(request.args.get('symbol') or 'SPX')); return jsonify({'ok':True,'status':'READY','tradeability':x.get('tradeability'),'blocking_issues':x.get('blocking_issues',[]),'evidence_completeness_score':x.get('evidence_completeness_score')})
    @app.get('/api/live-operations/dashboard')
    def live_operations_dashboard(): return jsonify(lo.dashboard(str(request.args.get('symbol') or 'SPX')))


    # APEX 16.7 — Governed Strategy Promotion & Champion/Challenger Control.
    @app.get('/api/strategy-promotion/status')
    def strategy_promotion_status(): return jsonify({'ok':True,**spg.status()})
    @app.post('/api/strategy-promotion/evaluate')
    def strategy_promotion_evaluate(): return jsonify({'ok':True,**spg.evaluate(request.get_json(silent=True) or {})})
    @app.post('/api/strategy-promotion/candidates')
    def strategy_promotion_candidates():
        b=request.get_json(silent=True) or {}; out=spg.submit_candidate(b,actor=str(b.get('actor') or 'API')); return j(out,201 if out.get('created') else 200)
    @app.post('/api/strategy-promotion/decisions')
    def strategy_promotion_decisions():
        b=request.get_json(silent=True) or {}; out=spg.record_decision(b,actor=str(b.get('actor') or 'API')); return j(out,201 if out.get('created') else 200)
    @app.post('/api/strategy-promotion/approvals')
    def strategy_promotion_approvals(): return jsonify(spg.approve(request.get_json(silent=True) or {}))
    @app.get('/api/strategy-promotion/history')
    def strategy_promotion_history(): return jsonify({'ok':True,'status':'READY','history':spg.history(int(request.args.get('limit',100)))})
    @app.get('/api/strategy-promotion/dashboard')
    def strategy_promotion_dashboard(): return jsonify(spg.dashboard())

    # APEX 16.8 — Broker-Synchronized Position State (read-only).
    @app.get('/api/broker-sync/status')
    def broker_sync_status(): return jsonify({'ok':True,**bsps.status()})
    @app.post('/api/broker-sync/evaluate')
    def broker_sync_evaluate(): return jsonify({'ok':True,**bsps.reconcile(request.get_json(silent=True) or {})})
    @app.post('/api/broker-sync/record')
    def broker_sync_record():
        b=request.get_json(silent=True) or {}; out=bsps.record(b,actor=str(b.get('actor') or 'API')); return j(out,201 if out.get('created') else 200)
    @app.get('/api/broker-sync/latest')
    def broker_sync_latest(): return jsonify(bsps.latest(str(request.args.get('account_id') or 'PRIMARY'),str(request.args.get('broker') or 'ETRADE')))
    @app.get('/api/broker-sync/history')
    def broker_sync_history(): return jsonify({'ok':True,'status':'READY','history':bsps.history(str(request.args.get('account_id') or 'PRIMARY'),int(request.args.get('limit',100)))})
    @app.get('/api/broker-sync/dashboard')
    def broker_sync_dashboard(): return jsonify(bsps.dashboard(str(request.args.get('account_id') or 'PRIMARY'),str(request.args.get('broker') or 'ETRADE')))

    # APEX 16.9 — Confirmation-Gated Execution.
    @app.get('/api/execution-gate/status')
    def execution_gate_status(): return jsonify({'ok':True,**cge.status()})
    @app.post('/api/execution-gate/intents')
    def execution_gate_intents():
        b=request.get_json(silent=True) or {}; out=cge.create_intent(b,str(b.get('idempotency_key') or '') or None); return j(out,201 if out.get('created') else 200)
    @app.post('/api/execution-gate/preview')
    def execution_gate_preview():
        b=request.get_json(silent=True) or {}; return jsonify(cge.preview(str(b.get('intent_id') or ''),b.get('gate_snapshot') or {},b.get('broker_preview') or {},int(b.get('ttl_seconds') or 120)))
    @app.post('/api/execution-gate/confirm')
    def execution_gate_confirm():
        b=request.get_json(silent=True) or {}; return jsonify(cge.confirm(str(b.get('intent_id') or ''),str(b.get('preview_record_id') or ''),str(b.get('confirmed_by') or ''),bool(b.get('acknowledgement')),int(b.get('ttl_seconds') or 90)))
    @app.post('/api/execution-gate/execute')
    def execution_gate_execute():
        b=request.get_json(silent=True) or {}; return jsonify(cge.execute(str(b.get('intent_id') or ''),str(b.get('confirmation_id') or ''),b.get('gate_snapshot') or {}))
    @app.get('/api/execution-gate/history')
    def execution_gate_history(): return jsonify({'ok':True,'status':'READY','history':cge.history(int(request.args.get('limit',100)))})
    @app.get('/api/execution-gate/dashboard')
    def execution_gate_dashboard(): return jsonify(cge.dashboard(int(request.args.get('limit',20))))

    # APEX 16.9.1 — E*TRADE Sandbox Execution Certification.
    @app.get('/api/sandbox-validation/status')
    def sandbox_validation_status(): return jsonify({'ok':True,**sev.status()})
    @app.post('/api/sandbox-validation/evaluate')
    def sandbox_validation_evaluate(): return jsonify({'ok':True,**sev.evaluate(request.get_json(silent=True) or {})})
    @app.post('/api/sandbox-validation/runs')
    def sandbox_validation_runs():
        b=request.get_json(silent=True) or {}; out=sev.record(b,actor=str(b.get('actor') or 'API')); return j(out,201 if out.get('created') else 200)
    @app.get('/api/sandbox-validation/latest')
    def sandbox_validation_latest(): return jsonify(sev.latest(str(request.args.get('account_id') or 'PRIMARY')))
    @app.get('/api/sandbox-validation/history')
    def sandbox_validation_history(): return jsonify({'ok':True,'status':'READY','history':sev.history(int(request.args.get('limit',50)))})
    @app.get('/api/sandbox-validation/dashboard')
    def sandbox_validation_dashboard(): return jsonify(sev.dashboard(str(request.args.get('account_id') or 'PRIMARY'),int(request.args.get('limit',10))))


    # APEX 17.0 — Institutional Autonomous Desk.
    @app.get('/api/autonomous-desk/status')
    def autonomous_desk_status(): return jsonify({'ok':True,**iad.status()})
    @app.post('/api/autonomous-desk/trades')
    def autonomous_desk_create_trade():
        b=request.get_json(silent=True) or {}; out=iad.create_trade(b,str(b.get('idempotency_key') or '') or None); return j(out,201 if out.get('created') else 200)
    @app.post('/api/autonomous-desk/trades/<desk_trade_id>/transition')
    def autonomous_desk_transition(desk_trade_id):
        b=request.get_json(silent=True) or {}; return jsonify(iad.transition(desk_trade_id,str(b.get('to_state') or ''),b.get('evidence') or {},actor=str(b.get('actor') or 'SYSTEM')))
    @app.post('/api/autonomous-desk/trades/<desk_trade_id>/artifacts')
    def autonomous_desk_artifact(desk_trade_id):
        b=request.get_json(silent=True) or {}; return jsonify(iad.attach_artifact(desk_trade_id,str(b.get('artifact_type') or ''),b.get('payload') or {},str(b.get('external_id') or '')))
    @app.get('/api/autonomous-desk/trades/<desk_trade_id>')
    def autonomous_desk_trade(desk_trade_id):
        out=iad.timeline(desk_trade_id); return j(out,200 if out.get('ok') else 404)
    @app.get('/api/autonomous-desk/history')
    def autonomous_desk_history(): return jsonify({'ok':True,'status':'READY','history':iad.history(int(request.args.get('limit',50)),request.args.get('state'))})
    @app.get('/api/autonomous-desk/dashboard')
    def autonomous_desk_dashboard(): return jsonify(iad.dashboard(int(request.args.get('limit',12))))

    # APEX 18.0 — Adaptive Intelligence (governed advisory learning).
    @app.get('/api/adaptive-intelligence/status')
    def adaptive_intelligence_status(): return jsonify({'ok':True,**ai18.status()})
    @app.post('/api/adaptive-intelligence/sessions')
    def adaptive_intelligence_record_session():
        out=ai18.record_session(request.get_json(silent=True) or {}); return j(out,201 if out.get('created') else 200)
    @app.get('/api/adaptive-intelligence/sessions')
    def adaptive_intelligence_sessions(): return jsonify({'ok':True,'sessions':ai18.sessions(int(request.args.get('limit',100)))})
    @app.post('/api/adaptive-intelligence/similarity')
    def adaptive_intelligence_similarity():
        b=request.get_json(silent=True) or {}; return jsonify(ai18.similar_sessions(b.get('profile') or {},int(b.get('top_k') or 5),b.get('exclude_date')))
    @app.get('/api/adaptive-intelligence/calibration')
    def adaptive_intelligence_calibration(): return jsonify(ai18.confidence_calibration(request.args.get('symbol','SPX')))
    @app.get('/api/adaptive-intelligence/playbooks')
    def adaptive_intelligence_playbooks(): return jsonify(ai18.playbook_rankings(request.args.get('symbol','SPX'),int(request.args.get('window',90))))
    @app.post('/api/adaptive-intelligence/edge')
    def adaptive_intelligence_edge(): return jsonify({'ok':True,**ai18.edge_score(request.get_json(silent=True) or {})})
    @app.post('/api/adaptive-intelligence/reviews')
    def adaptive_intelligence_review():
        out=ai18.self_evaluate(request.get_json(silent=True) or {}); return j(out,201 if out.get('created') else 200)
    @app.post('/api/adaptive-intelligence/journals')
    def adaptive_intelligence_journal():
        out=ai18.daily_journal(request.get_json(silent=True) or {}); return j(out,201 if out.get('created') else 200)
    @app.post('/api/adaptive-intelligence/dashboard')
    def adaptive_intelligence_dashboard():
        b=request.get_json(silent=True) or {}; return jsonify(ai18.dashboard(str(b.get('symbol') or 'SPX'),b.get('current_profile') or {},b.get('raw_confidence')))

    @app.get('/api/trading-desk-ux/status')
    def trading_desk_ux_status(): return jsonify({'ok':True,**itdux.status()})
    @app.get('/api/trading-desk-ux/workspace')
    def trading_desk_ux_workspace(): return jsonify(itdux.workspace(request.args.get('symbol','SPX')))

    @app.get('/apex_os/institutional_trading_desk')
    @app.get('/apex_os/trading_desk')
    @app.get('/apex_os/mission_control')
    def institutional_trading_desk_page(): return render_template('institutional_trading_desk.html')

    @app.get('/apex_os/decision_intelligence')
    def decision_intelligence_dashboard(): return render_template('decision_intelligence_core.html')

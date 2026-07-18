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

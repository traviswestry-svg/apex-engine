import json
from engine.evidence_pipeline import _connect
from engine.historical_effectiveness_observatory import build_observatory


def _seed(path):
    snap1={"setup":"ORB_RECLAIM","trade_horizon_intelligence":{"horizons":{"SCALP":{"direction":"BULLISH"},"INTRADAY":{"direction":"BULLISH"},"SWING":{"direction":"BEARISH"}}},"gamma_regime":"POSITIVE"}
    snap2={"setup":"ORB_RECLAIM","trade_horizon_intelligence":{"horizons":{"SCALP":{"direction":"BEARISH"},"INTRADAY":{"direction":"BEARISH"}}},"gamma_regime":"NEGATIVE"}
    with _connect(path) as c:
        c.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?,?,?)",('d1','2026-08-10T14:00:00+00:00','SPX','MARKET_OPEN','BULLISH','TRADE',6400,80,1,json.dumps(snap1),'GRADED'))
        c.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?,?,?)",('d2','2026-08-10T15:00:00+00:00','SPX','MARKET_OPEN','BEARISH','TRADE',6395,60,1,json.dumps(snap2),'GRADED'))
        c.execute("INSERT INTO grading_results(decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json) VALUES(?,?,?,?,?,?)",('d1','2026-08-10T14:05:00+00:00','GRADED',None,300,json.dumps({'won':True,'direction_correct':True,'directional_move':4,'mfe':6,'mae':-1})))
        c.execute("INSERT INTO grading_results(decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json) VALUES(?,?,?,?,?,?)",('d2','2026-08-10T15:05:00+00:00','GRADED',None,300,json.dumps({'won':False,'direction_correct':False,'directional_move':-2,'mfe':1,'mae':-4})))


def test_observatory_uses_only_graded_evidence(tmp_path):
    p=tmp_path/'e.db'; _seed(p)
    out=build_observatory(path=p, minimum_sample=2)
    assert out['ok'] is True
    assert out['overall']['sample_size']==2
    assert out['overall']['hit_rate']==50.0
    assert out['overall']['mean_evidence_score']==70.0
    assert out['overall']['calibration_gap_points']==20.0
    assert out['status']=='READY'


def test_horizon_directions_are_measured_without_time_inference(tmp_path):
    p=tmp_path/'e.db'; _seed(p)
    out=build_observatory(path=p, minimum_sample=1)
    h={x['value']:x for x in out['breakdowns']['horizon']}
    assert h['SCALP']['sample_size']==2
    assert h['INTRADAY']['sample_size']==2
    assert h['SWING']['sample_size']==1
    assert h['SWING']['hit_rate']==0.0
    assert out['guardrails']['backfills_history'] is False

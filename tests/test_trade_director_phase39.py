from pathlib import Path
from engine.trade_director_subminute_execution import evaluate_subminute_execution


def bars(direction="CALL", count=6, stall=False):
    out=[]
    price=6400.0
    for i in range(count):
        if direction == "CALL":
            o=price; c=price + (0.10 if stall else 0.55); h=c + (0.8 if stall else 0.08); l=o-0.05
        else:
            o=price; c=price - (0.10 if stall else 0.55); h=o+0.05; l=c-(0.8 if stall else 0.08)
        out.append({"open":o,"high":h,"low":l,"close":c,"volume":100+i*15})
        price=c
    return out


def setup(direction="CALL"):
    return {"direction":direction,"setup_valid":True,"risk_eligible":True,"data_fresh":True,
            "spread_ok":True,"one_minute_setup_score":88,"confidence":90,
            "premium_target_low":1,"premium_target_high":3,"max_hold_seconds":180}


def test_subminute_confirms_entry_only_after_higher_timeframe_gate():
    r=evaluate_subminute_execution(setup=setup(),bars_15s=bars(),bars_30s=bars())
    assert r["action"] == "ENTRY_ELIGIBLE"
    assert r["direction_source"] == "HIGHER_TIMEFRAME_ONLY"
    assert r["broker_action"] == "NONE"


def test_subminute_cannot_create_direction():
    s=setup(); s["direction"]="NEUTRAL"
    r=evaluate_subminute_execution(setup=s,bars_15s=bars(),bars_30s=bars())
    assert r["action"] == "WAIT"
    assert "direction" in r["gate_failures"][0].lower()


def test_stall_after_profit_target_recommends_profit():
    r=evaluate_subminute_execution(setup=setup(),bars_15s=bars(stall=True),bars_30s=bars(stall=True),
        position={"status":"OPEN","side":"CALL","option_entry_price":10,"time_in_trade_seconds":70},current_premium=11.35)
    assert r["action"] in {"TAKE_PROFIT","EXIT_OR_TIGHTEN"}
    assert r["premium_change"] == 1.35


def test_max_three_minute_timebox():
    r=evaluate_subminute_execution(setup=setup(),bars_15s=bars(),bars_30s=bars(),
        position={"status":"OPEN","side":"CALL","option_entry_price":10,"time_in_trade_seconds":181},current_premium=10.4)
    assert r["action"] == "EXIT_OR_REASSESS"


def test_phase39_route_registered():
    text=Path("app.py").read_text(encoding="utf-8")
    assert "TRADE_DIRECTOR_PHASE39_AVAILABLE" in text
    assert '/api/subminute-execution/evaluate' in text

import datetime as dt
from engine.execution.complex_options import build_ticket, validate_ticket, ComplexLeg, ComplexOrderIntent
from engine.brokers.etrade_adapter import ETradeAdapter


def c(side,strike,bid,ask):
    return {"side":side,"strike":strike,"bid":bid,"ask":ask,"mid":round((bid+ask)/2,2),
            "osi_key":f"SPXW  260720{side[0]}{int(strike*1000):08d}","expiration":"2026-07-20",
            "quote_age_seconds":2,"source":"etrade"}


def recommendation():
    return {"strategy":"IRON_CONDOR","strategy_label":"Iron Condor","legs":{"put_long":7415,"put_short":7425,"call_short":7490,"call_long":7500}}


def test_arm_iron_condor_resolves_four_explicit_legs():
    puts=[c("PUT",7415,.70,.80),c("PUT",7425,1.20,1.30)]
    calls=[c("CALL",7490,1.35,1.45),c("CALL",7500,.75,.85)]
    t=build_ticket(recommendation=recommendation(),expiration="2026-07-20",call_contracts=calls,put_contracts=puts,quantity=1,now=dt.date(2026,7,20))
    assert t["ready_for_preview"] is True
    assert t["dte"] == 0
    assert [x["action"] for x in t["intent"]["legs"]] == ["BUY_OPEN","SELL_OPEN","SELL_OPEN","BUY_OPEN"]
    assert [x["side"] for x in t["intent"]["legs"]] == ["PUT","PUT","CALL","CALL"]
    assert t["economics"]["max_loss"] is not None


def test_missing_contract_blocks_execution():
    t=build_ticket(recommendation=recommendation(),expiration="2026-07-20",call_contracts=[],put_contracts=[],now=dt.date(2026,7,20))
    assert t["state"] == "ARMED_EXECUTION_BLOCKED"
    assert not t["ready_for_preview"]
    assert len(t["errors"]) >= 4


def test_ticket_validation_rejects_missing_osi():
    assert validate_ticket({"intent":{"limit_price":1,"legs":[{"action":"BUY_OPEN","side":"CALL","expiration":"2026-07-20","quantity":1}]}})


def test_etrade_complex_payload_is_single_order_with_four_instruments(monkeypatch):
    a=ETradeAdapter()
    legs=tuple(ComplexLeg(action,side,strike,"2026-07-20",1,osi_key=f"KEY{i}") for i,(action,side,strike) in enumerate([
        ("BUY_OPEN","PUT",7415),("SELL_OPEN","PUT",7425),("SELL_OPEN","CALL",7490),("BUY_OPEN","CALL",7500)],1))
    intent=ComplexOrderIntent("SPX","IRON_CONDOR",legs,1,"NET_CREDIT",1.0)
    body=a._complex_order_payload(intent,True)
    order=body["PreviewOrderRequest"]["Order"][0]
    assert order["priceType"] == "NET_CREDIT"
    assert len(order["Instrument"]) == 4
    assert order["Instrument"][1]["orderAction"] == "SELL_OPEN"

from pathlib import Path


def test_phase36_routes_registered():
    text = Path("app.py").read_text(encoding="utf-8")
    assert '/api/position/momentum-lifecycle' in text
    assert '/api/entry-quality' in text
    assert 'TRADE_DIRECTOR_PHASE36_AVAILABLE' in text


def test_assistant_contains_precision_entry_lifecycle():
    text = Path("templates/assistant.html").read_text(encoding="utf-8")
    assert 'Precision Entry & Momentum Lifecycle' in text
    assert 'MOMENTUM_BURST' in text
    assert 'premium_adverse_exit:2.5' in text
    assert 'premium_profit_target:2.0' in text

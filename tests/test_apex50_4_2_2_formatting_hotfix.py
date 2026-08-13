from engine.daily_key_levels import _fmt


def test_fmt_numeric():
    assert _fmt(7437.53) == "7,437.53"


def test_fmt_categorical_confidence():
    assert _fmt("HIGH") == "HIGH"


def test_fmt_gamma_state():
    assert _fmt("neutral_gamma") == "neutral_gamma"

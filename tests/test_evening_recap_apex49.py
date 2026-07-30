import datetime as dt

from engine import evening_recap as er


def _bar(hour, minute, o, h, l, c, day=29):
    ts = dt.datetime(2026, 7, day, hour, minute, tzinfo=er.ET)
    return {"t": int(ts.timestamp() * 1000), "o": o, "h": h, "l": l, "c": c}


def morning():
    return {
        "session_date": "2026-07-29",
        "markdown": "Expected regime: Balanced Auction due to positive gamma.",
        "structured": {
            "spot": 6400,
            "expected_move": {"one_sigma": 20, "upper": 6420, "lower": 6380},
            "levels": [
                {"kind": "POC", "label": "POC", "price": 6400},
                {"kind": "CALL_WALL", "label": "Call Wall", "price": 6425},
            ],
        },
    }


def test_actual_session_and_comparison_are_deterministic():
    bars = [
        _bar(9, 30, 6400, 6405, 6398, 6402),
        _bar(10, 0, 6402, 6410, 6399, 6401),
        _bar(15, 59, 6401, 6404, 6397, 6400),
    ]
    result = er.build_comparison(morning(), bars, "2026-07-29")
    assert result["actual"]["available"] is True
    assert result["actual_regime"] in {"Balanced Auction", "Compression", "Mean Reversion"}
    assert result["score"] is not None
    poc = next(x for x in result["levels"] if x["kind"] == "POC")
    assert poc["touched"] is True


def test_missing_bars_never_fabricates_outcome():
    result = er.build_comparison(morning(), [], "2026-07-29")
    assert result["actual"]["available"] is False
    assert result["actual_regime"] == "Unavailable"


def test_regime_extraction():
    assert er.extract_projected_regime("Regime: Event Driven") == "Event Driven"
    assert er.extract_projected_regime("No classification present") is None

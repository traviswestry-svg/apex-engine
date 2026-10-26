import datetime as dt
from engine.evening_recap import build_comparison, render_deterministic_markdown


def bars(day="2026-10-26"):
    return [{"t": int(dt.datetime.fromisoformat(day + "T14:00:00+00:00").timestamp() * 1000),
             "o": 7639.70, "h": 7702.13, "l": 7639.70, "c": 7660}]


def morning():
    return {"structured": {"spot": 7622.74, "forecast_regime": "Balanced Auction",
                            "expected_move": {"one_sigma": 50.06, "lower": 7572.68, "upper": 7672.80}}}


def test_oct26_error_decomposition_does_not_change_score():
    result = build_comparison(morning(), bars(), "2026-10-26")
    r = result["forecast_error_diagnostics"]["range"]
    m = result["forecast_error_diagnostics"]["movement"]
    assert r["high_error_points"] == 29.33
    assert r["low_error_points"] == 67.02
    assert r["width_error_points"] == -37.69
    assert r["center_error_points"] == 48.18
    assert m["actual_max_excursion_points"] == 79.39
    assert m["error_points"] == 29.33
    assert result["score"] == 47.4
    assert result["forecast_error_diagnostics"]["regime"]["exact_match"] is False
    assert next(c for c in result["checks"] if c["key"] == "regime")["correct"] is True
    assert "Forecast Error Attribution" in render_deterministic_markdown("2026-10-26", result)


def test_missing_forecast_fails_closed_without_invented_metrics():
    result = build_comparison({"structured": {}}, bars(), "2026-10-26")
    diag = result["forecast_error_diagnostics"]
    assert not diag["range"]["available"]
    assert not diag["movement"]["available"]
    assert result["score"] is None


def test_no_bars_fails_closed():
    result = build_comparison(morning(), [], "2026-10-26")
    assert not result["forecast_error_diagnostics"]["range"]["available"]
    assert not result["forecast_error_diagnostics"]["movement"]["available"]

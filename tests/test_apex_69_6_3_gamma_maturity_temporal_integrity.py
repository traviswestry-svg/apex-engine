from datetime import date

from engine.gamma import _expiration_dte, build_gamma_from_quantdata_response


def _payload():
    return {"data": {"SPX": {"stockPrice": 6500, "exposureMap": {
        "2026-08-27": {"6500": {"callExposure": 100, "putExposure": -20}},
        "2026-08-28": {"6500": {"callExposure": 10, "putExposure": -2}},
        "2026-08-29": {"6500": {"callExposure": 5, "putExposure": -1}},
        "2026-09-04": {"6500": {"callExposure": 2, "putExposure": -1}},
    }}}}


def test_expired_expiration_is_signed_not_clamped_to_zero():
    assert _expiration_dte("2026-08-27", date(2026, 8, 28)) == -1
    assert _expiration_dte("2026-08-28", date(2026, 8, 28)) == 0
    assert _expiration_dte("2026-08-29", date(2026, 8, 28)) == 1


def test_expired_gamma_is_observable_but_excluded_from_current_concentration():
    g = build_gamma_from_quantdata_response(_payload(), "SPX", as_of=date(2026, 8, 28))
    ts = g["gamma_term_structure"]
    m = ts["maturity_concentration"]
    assert ts["as_of"] == "2026-08-28"
    assert ts["expired_expirations_excluded"] == 1
    expired = [r for r in ts["expirations"] if r["expiration"] == "2026-08-27"][0]
    assert expired["dte"] == -1 and expired["expired"] is True
    assert ts["immediate"]["expiration"] == "2026-08-28"
    assert 0 < m["zero_dte_gamma_share"] < m["zero_one_dte_gamma_share"] < 1


def test_explicit_as_of_prevents_wall_clock_drift():
    a = build_gamma_from_quantdata_response(_payload(), "SPX", as_of=date(2026, 8, 28))
    b = build_gamma_from_quantdata_response(_payload(), "SPX", as_of=date(2026, 8, 29))
    assert a["gamma_term_structure"]["maturity_concentration"] != b["gamma_term_structure"]["maturity_concentration"]
    assert a["gamma_term_structure"]["as_of"] == "2026-08-28"
    assert b["gamma_term_structure"]["as_of"] == "2026-08-29"

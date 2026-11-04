"""Frozen-source quality tests; all input observations are synthetic."""
import datetime as dt
import unittest
from types import SimpleNamespace

from engine.expected_move_source_integrity import audit
from engine.daily_key_levels_adapters import compute_atm_straddle_iv_details
from engine.options.options_data_bus import normalize_contract

DECISION = "2026-11-03T14:00:00+00:00"
TS = "2026-11-03T13:59:45+00:00"


def evidence(*, ts=TS, method="mid", expiration="2026-11-03", price=10.0):
    leg = {"bid": price - 1, "ask": price + 1, "mid": price, "last": price,
           "quote_timestamp": ts, "source": "polygon", "expiration": expiration,
           "method": method, "contract_id": "O:SPXWTEST"}
    return {"provider": "polygon", "expiration": "2026-11-03",
            "captured_at": "2026-11-03T13:59:50+00:00",
            "atm_straddle_premium": 20., "atm_iv": .2,
            "time_to_expiry_year_fraction": .0002,
            "quote_selection": {"status": "ok", "call": dict(leg), "put": dict(leg)}}


class TestSourceAudit(unittest.TestCase):
    def setUp(self):
        self.frozen = {"selected_path": "STRADDLE_FIRST", "selected_one_sigma": 17., "reference_spot": 7500.}

    def test_verified_quote_pair(self):
        result = audit(evidence(), self.frozen, decision_at=DECISION)
        self.assertEqual(result["status"], "SOURCE_VERIFIED")
        self.assertEqual(result["quote_legs"]["call"]["quote_age_at_decision_seconds"], 15.)

    def test_missing_timestamp_never_substitutes_capture_time(self):
        result = audit(evidence(ts=None), self.frozen, decision_at=DECISION)
        self.assertEqual(result["status"], "DEGRADED_SOURCE_EVIDENCE")
        self.assertIsNone(result["quote_legs"]["call"]["provider_quote_timestamp"])
        self.assertIn("MISSING_PROVIDER_QUOTE_TIMESTAMP_CALL", result["issues"])

    def test_future_timestamp_fails(self):
        result = audit(evidence(ts="2026-11-03T14:01:00+00:00"), self.frozen, decision_at=DECISION)
        self.assertEqual(result["status"], "REJECTED_INTEGRITY")

    def test_old_quote_degrades(self):
        result = audit(evidence(ts="2026-11-03T13:45:00+00:00"), self.frozen, decision_at=DECISION)
        self.assertIn("STALE_QUOTE_CALL", result["issues"])
        self.assertEqual(result["status"], "DEGRADED_SOURCE_EVIDENCE")

    def test_last_trade_fallback_degrades(self):
        result = audit(evidence(method="last_trade"), self.frozen, decision_at=DECISION)
        self.assertIn("LAST_TRADE_FALLBACK_CALL", result["issues"])

    def test_expiry_mismatch_rejects(self):
        result = audit(evidence(expiration="2026-11-04"), self.frozen, decision_at=DECISION)
        self.assertEqual(result["status"], "REJECTED_INTEGRITY")

    def test_inconsistent_frozen_move_rejects(self):
        result = audit(evidence(), dict(self.frozen, selected_one_sigma=35.), decision_at=DECISION)
        self.assertIn("STRADDLE_SIGMA_MISMATCH", result["issues"])

    def test_missing_options_is_explicit(self):
        result = audit(None, self.frozen, decision_at=DECISION)
        self.assertNotEqual(result["status"], "SOURCE_VERIFIED")
        self.assertTrue(result["advisory_only"])

    def test_iv_fallback_checks_formula_without_creating_quotes(self):
        src = evidence()
        src["atm_iv"] = .2
        src["quote_selection"] = {}
        f = dict(self.frozen, selected_path="IV_FALLBACK",
                 selected_one_sigma=7500 * .2 * (.0002 ** .5))
        result = audit(src, f, decision_at=DECISION)
        self.assertNotIn("IV_SIGMA_MISMATCH", result["issues"])
        self.assertFalse(result["provider_source_verified"])

    def test_polygon_nanoseconds_round_trip_provenance(self):
        ts = int(dt.datetime(2026, 11, 3, 13, 59, 45, tzinfo=dt.timezone.utc).timestamp() * 1e9)
        contract = normalize_contract({"strike": 7500, "side": "CALL", "expiration": "2026-11-03",
                                       "bid": 9, "ask": 11, "last_updated": ts},
                                      source="polygon", now=dt.datetime(2026, 11, 3, 14, tzinfo=dt.timezone.utc))
        self.assertEqual(contract.quote_timestamp, TS)
        self.assertAlmostEqual(contract.quote_age_seconds, 15.)

    def test_atm_details_preserve_normalized_leg_identity(self):
        args = {"strike": 7500, "bid": 9, "ask": 11, "mid": 10, "last": 10,
                "expiration": "2026-11-03", "quote_timestamp": TS, "source": "polygon",
                "quote_age_seconds": 15, "osi_key": "O:SPXWTEST", "iv": .2}
        call = SimpleNamespace(**args)
        put = SimpleNamespace(**args)
        premium, _, details = compute_atm_straddle_iv_details([call], [put], 7500)
        self.assertEqual(premium, 20.)
        self.assertEqual(details["call"]["quote_timestamp"], TS)
        self.assertEqual(details["put"]["expiration"], "2026-11-03")


if __name__ == "__main__":
    unittest.main()

import json
from dataclasses import dataclass

from engine.daily_key_levels_adapters import compute_atm_straddle_iv_details


@dataclass
class Contract:
    strike: float
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    last: float | None = None
    iv: float | None = None


def test_expected_move_diagnostics_are_json_serializable_with_missing_quotes():
    calls = [Contract(strike=7300, last=20.0)]
    puts = [Contract(strike=7300, last=18.0)]
    straddle, iv, diagnostics = compute_atm_straddle_iv_details(calls, puts, 7302.0)
    assert straddle == 38.0
    assert diagnostics["call"]["bid"] is None
    assert diagnostics["put"]["ask"] is None
    json.dumps(diagnostics)

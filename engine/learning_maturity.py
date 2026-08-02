"""Shared APEX learning-readiness contract.

Prevents thin samples from being presented as mature calibrated intelligence.
"""
from __future__ import annotations
from typing import Any, Dict, Optional


def maturity_contract(sample_count: int, minimum_sample: int, *, source: Optional[str] = None,
                      last_observation_at: Optional[str] = None, degraded: bool = False) -> Dict[str, Any]:
    n = max(0, int(sample_count or 0))
    minimum = max(1, int(minimum_sample or 1))
    if degraded:
        maturity = "DEGRADED"
    elif n == 0:
        maturity = "UNINITIALIZED"
    elif n < minimum:
        maturity = "EARLY_SAMPLE"
    else:
        maturity = "STATISTICALLY_USABLE"
    return {
        "sample_count": n,
        "minimum_sample": minimum,
        "remaining_samples": max(0, minimum - n),
        "maturity": maturity,
        "source": source or "UNKNOWN",
        "last_observation_at": last_observation_at,
        "statistically_usable": maturity == "STATISTICALLY_USABLE",
        "display_policy": "DO_NOT_RENDER_AS_CALIBRATED_CONFIDENCE" if n < minimum else "CALIBRATED_CONFIDENCE_ALLOWED",
    }

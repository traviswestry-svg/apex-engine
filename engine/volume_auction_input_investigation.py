"""Bounded, observational diagnostics for the existing volume/auction input path.

No provider requests, retries, recalculations, or trading authority. A liveness
fingerprint alone cannot identify a root cause; retain timing and input status.
"""
from __future__ import annotations
from typing import Any, Mapping, Sequence

SCHEMA = "APEX_VOLUME_AUCTION_INPUT_INVESTIGATION_V1"


def analyze(*, bundle: Mapping[str, Any] | None, timed_out: Sequence[str],
            duration_ms: float | None, liveness: Mapping[str, Any] | None = None,
            fetch_timeout_seconds: float | None = None) -> dict[str, Any]:
    bundle = bundle or {}
    profile = bundle.get("profile") or {}
    auction = bundle.get("auction") or {}
    levels = profile.get("levels") or {}
    liveness = liveness or {}
    statuses = {x.get("component"): x.get("status") for x in liveness.get("components", [])
                if isinstance(x, dict)}
    timed_out_names = set(timed_out)
    if "volume_profile" in timed_out_names:
        state = "FETCH_TIMEOUT_OR_EXCEPTION"
    elif not bundle:
        state = "EMPTY_VOLUME_BUNDLE"
    elif not profile:
        state = "MISSING_VOLUME_PROFILE"
    elif not auction:
        state = "MISSING_AUCTION"
    elif statuses.get("volume_profile") == "FROZEN" or statuses.get("auction") == "FROZEN":
        state = "UNCHANGED_COMPONENTS_NEED_SOURCE_FRESHNESS_CHECK"
    else:
        state = "INPUTS_PRESENT_NO_FAILURE_PROVEN"
    return {
        "schema": SCHEMA, "state": state, "read_only": True,
        "writes_evidence": False, "changes_trade_decisions": False,
        "execution_authority": False, "provider_requests_added": 0,
        "provider_fetch_timed_out_or_failed": "volume_profile" in timed_out_names,
        "fetch_duration_ms": duration_ms, "fetch_deadline_seconds": fetch_timeout_seconds,
        "bundle_present": bool(bundle), "profile_present": bool(profile),
        "auction_present": bool(auction), "source": profile.get("source"),
        "profile_quality_flags": profile.get("quality_flags") or [],
        "levels_present": {k: levels.get(k) is not None for k in ("poc", "vah", "val")},
        "volume_profile_liveness": statuses.get("volume_profile"),
        "auction_liveness": statuses.get("auction"),
        "note": "A timeout and an unchanged fingerprint have different meanings; neither proves a vendor outage.",
    }

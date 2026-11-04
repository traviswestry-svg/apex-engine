"""Read-only frozen expected-move input provenance. No market calls or authority.

All quality decisions in this module are advisory: the existing forecast and
straddle-first/IV-fallback selection remain unchanged. Missing source metadata
is never replaced with current time or data from a subsequent session.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math

SCHEMA = "EXPECTED_MOVE_DECISION_TIME_SOURCE_INTEGRITY_V1"
MAX_QUOTE_AGE_SECONDS = 120.0  # research threshold only, not production gating
MAX_SPREAD_PCT = 25.0  # research threshold only


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def audit(evidence, frozen, *, decision_at):
    """Verify quote components against pre-outcome frozen arithmetic only.

    Never confuses provider event time with capture/ingestion time. A missing
    timestamp cannot yield VERIFIED evidence, even with a positive mid price.
    """
    src = evidence if isinstance(evidence, dict) else {}
    detail = src.get("quote_selection") if isinstance(src.get("quote_selection"), dict) else {}
    path = str((frozen or {}).get("selected_path") or "UNAVAILABLE")
    issues = []
    def issue(value):
        if value not in issues:
            issues.append(value)

    decision = timestamp(decision_at)
    expiration = src.get("expiration") if isinstance(src.get("expiration"), str) else None
    if expiration:
        try:
            from zoneinfo import ZoneInfo
            from datetime import date
            if decision and date.fromisoformat(expiration) < decision.astimezone(ZoneInfo("America/New_York")).date():
                issue("EXPIRED_OPTION_EXPIRATION")
        except ValueError:
            issue("INVALID_OPTION_EXPIRATION")
    tfrac = number(src.get("time_to_expiry_year_fraction"))
    premium = number(src.get("atm_straddle_premium"))
    iv = number(src.get("atm_iv"))
    selected_sigma = number((frozen or {}).get("selected_one_sigma"))
    spot = number((frozen or {}).get("reference_spot"))
    quote_at = []
    legs = {}
    for side in ("call", "put"):
        raw = detail.get(side) if isinstance(detail.get(side), dict) else {}
        bid, ask, mid = (number(raw.get(k)) for k in ("bid", "ask", "mid"))
        last = number(raw.get("last"))
        method = raw.get("method")
        observed = timestamp(raw.get("quote_timestamp"))
        age = (decision - observed).total_seconds() if decision and observed else None
        if observed is not None:
            quote_at.append(observed)
        if observed is None:
            issue("MISSING_PROVIDER_QUOTE_TIMESTAMP_" + side.upper())
        elif age is not None and age < 0:
            issue("FUTURE_QUOTE_TIMESTAMP_" + side.upper())
        elif age is not None and age > MAX_QUOTE_AGE_SECONDS:
            issue("STALE_QUOTE_" + side.upper())
        spread = (100 * (ask - bid) / mid if bid is not None and ask is not None and mid and mid > 0 else None)
        if bid is not None and ask is not None and ask < bid:
            issue("CROSSED_MARKET_" + side.upper())
        if spread is not None and spread > MAX_SPREAD_PCT:
            issue("WIDE_SPREAD_" + side.upper())
        if method == "last_trade":
            issue("LAST_TRADE_FALLBACK_" + side.upper())
        elif method != "mid":
            issue("QUOTE_PRICE_METHOD_UNVERIFIED_" + side.upper())
        if method == "mid" and (bid is None or ask is None or mid is None or ask < bid or mid <= 0):
            issue("MID_NOT_TWO_SIDED_" + side.upper())
        if not raw.get("contract_id"):
            issue("MISSING_CONTRACT_ID_" + side.upper())
        if not raw.get("expiration"):
            issue("MISSING_LEG_EXPIRATION_" + side.upper())
        elif expiration and raw.get("expiration") != expiration:
            issue("EXPIRATION_MISMATCH_" + side.upper())
        if not raw.get("source"):
            issue("MISSING_LEG_PROVIDER_" + side.upper())
        elif src.get("provider") and raw.get("source") != src.get("provider"):
            issue("PROVIDER_MISMATCH_" + side.upper())
        legs[side] = {
            "contract_id": raw.get("contract_id"), "source": raw.get("source"),
            "expiration": raw.get("expiration"), "bid": bid, "ask": ask, "mid": mid,
            "last": last, "method": method, "spread_percent": round(spread, 4) if spread is not None else None,
            "provider_quote_timestamp": observed.isoformat() if observed else None,
            "quote_age_at_decision_seconds": round(age, 3) if age is not None else None,
            "provider_reported_quote_age_seconds": number(raw.get("quote_age_seconds")),
        }
    if not expiration:
        issue("MISSING_OPTION_EXPIRATION")
    if tfrac is None or tfrac <= 0:
        issue("MISSING_VALID_TIME_TO_EXPIRY")
    if detail.get("status") != "ok":
        issue("NO_VERIFIED_ATM_PAIR")
    if path == "STRADDLE_FIRST":
        if premium is None or premium <= 0:
            issue("MISSING_STRADDLE_PREMIUM")
        elif selected_sigma is None or not math.isclose(selected_sigma, 0.85 * premium, rel_tol=1e-7, abs_tol=.01):
            issue("STRADDLE_SIGMA_MISMATCH")
        prices = []
        for side in ("call", "put"):
            row = legs[side]
            px = row["mid"] if row["method"] == "mid" else row["last"] if row["method"] == "last_trade" else None
            prices.append(px)
        if premium is not None and all(px is not None for px in prices) and not math.isclose(premium, sum(prices), abs_tol=.01):
            issue("STRADDLE_LEG_SUM_MISMATCH")
    elif path == "IV_FALLBACK":
        if spot is None or spot <= 0 or iv is None or iv <= 0 or not tfrac or tfrac <= 0:
            issue("MISSING_IV_FALLBACK_INPUTS")
        elif selected_sigma is None or not math.isclose(selected_sigma, spot * iv * math.sqrt(tfrac), rel_tol=1e-6, abs_tol=.01):
            issue("IV_SIGMA_MISMATCH")
    else:
        issue("EXPECTED_MOVE_PATH_UNAVAILABLE")
    severe = any(x.startswith(("FUTURE_", "STRADDLE_SIGMA_", "STRADDLE_LEG_SUM_", "IV_SIGMA_", "EXPIRATION_MISMATCH", "PROVIDER_MISMATCH", "CROSSED_", "MID_NOT_", "EXPIRED_", "INVALID_OPTION_")) for x in issues)
    status = "REJECTED_INTEGRITY" if severe else "DEGRADED_SOURCE_EVIDENCE" if issues else "SOURCE_VERIFIED"
    return {
        "schema": SCHEMA, "mode": "READ_ONLY_PRE_OUTCOME_SOURCE_AUDIT", "status": status,
        "selected_path": path, "provider": src.get("provider"),
        "option_expiration": expiration, "decision_at": decision.isoformat() if decision else None,
        "capture_timestamp": src.get("captured_at"), "earliest_provider_quote_at": min(quote_at).isoformat() if quote_at else None,
        "time_to_expiry_year_fraction": tfrac, "source_atm_straddle_premium": premium,
        "source_atm_iv": iv, "selected_one_sigma": selected_sigma,
        "quote_legs": legs, "issues": issues,
        "limits": {"max_quote_age_seconds": MAX_QUOTE_AGE_SECONDS, "max_spread_percent": MAX_SPREAD_PCT},
        "provider_source_verified": status == "SOURCE_VERIFIED",
        "advisory_only": True, "official_forecast_mutated": False,
        "note": "Quote age is measured from provider event timestamp to frozen decision time; no timestamp substitution or historical backfill.",
    }

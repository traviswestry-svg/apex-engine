"""APEX 50 data-completeness report builders."""
from __future__ import annotations

from typing import Any
from .data_registry import DataRegistry


def _present(value: Any) -> bool:
    return value not in (None, "", "[FEED REQUIRED]")


def build_morning_registry(*, structured: dict, options_feed: dict, flow: dict,
                           overnight_meta: dict, provider_flags: dict) -> DataRegistry:
    reg = DataRegistry()
    levels = structured.get("levels") or []
    by_kind = {}
    for level in levels:
        by_kind.setdefault(level.get("kind"), level)

    def add_level(kind: str, source: str, reason: str) -> None:
        row = by_kind.get(kind) or {}
        value = row.get("price")
        reg.put(kind, value if _present(value) else None, source=source,
                confidence=1.0 if _present(value) else 0.0, reason=reason)

    for kind in ("prev_day_high", "prev_day_low", "prev_close", "prev_open"):
        add_level(kind, "polygon_indices", "SPX daily aggregate unavailable")
    settlement = by_kind.get("prev_settlement") or {}
    settlement_value = settlement.get("price")
    reg.put("prev_settlement", settlement_value if _present(settlement_value) else None,
            source="massive_futures", confidence=0.75 if _present(settlement_value) else 0.0,
            fallback=bool(overnight_meta.get("settlement_method")),
            reason="ES official settlement unavailable; previous-session close proxy was also unavailable")
    for kind in ("overnight_high", "overnight_low", "overnight_mid"):
        add_level(kind, "massive_futures", overnight_meta.get("reason") or "ES Globex bars unavailable")
    gamma_conf = str(flow.get("zero_gamma_confidence") or "").upper()
    no_crossing = gamma_conf != "HIGH" and flow.get("active_gamma_flip") in (None, "")
    for kind in ("gamma_flip", "zero_gamma", "volatility_trigger"):
        row = by_kind.get(kind) or {}; value = row.get("price")
        if no_crossing and not _present(value):
            reg.put(kind, None, source="quantdata", confidence=1.0, applicable=False,
                    reason="Not applicable: QuantData curve had no confirmed local zero crossing")
        else:
            add_level(kind, "quantdata", "QuantData did not return an authoritative local crossing")
    for kind in ("call_wall", "put_wall", "high_gamma_strike", "low_gamma_strike"):
        add_level(kind, "quantdata", "QuantData exposure curve did not yield a value")
    for kind in ("developing_poc", "vah", "val", "prev_poc", "composite_poc", "composite_vah", "composite_val"):
        add_level(kind, "apex_volume_profile", "Profile history is not yet persisted for this field")

    em = structured.get("expected_move") or {}
    for key in ("one_sigma", "upper", "lower", "confidence"):
        val = em.get(key)
        reg.put(f"expected_move_{key}", val if _present(val) else None,
                source="polygon_options", confidence=1.0 if _present(val) else 0.0,
                reason=options_feed.get("error") or (options_feed.get("diagnostics") or {}).get("reason") or "ATM call/put quote or IV was unavailable")

    for provider, configured in provider_flags.items():
        reg.put(f"provider_{provider}_configured", bool(configured), source="configuration",
                confidence=1.0, reason=None)
    reg.put("options_contracts", (options_feed.get("call_contracts", 0) + options_feed.get("put_contracts", 0)) or None,
            source="polygon_options", reason=options_feed.get("error") or "No normalized option contracts")
    reg.put("gamma_regime", structured.get("gamma_regime"), source="quantdata",
            reason="Gamma regime unavailable")
    return reg

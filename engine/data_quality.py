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
    add_level("prev_settlement", "massive_futures", "ES settlement was not supplied")
    for kind in ("overnight_high", "overnight_low", "overnight_mid"):
        add_level(kind, "massive_futures", overnight_meta.get("reason") or "ES Globex bars unavailable")
    for kind in ("gamma_flip", "zero_gamma", "call_wall", "put_wall", "high_gamma_strike", "low_gamma_strike", "volatility_trigger"):
        add_level(kind, "quantdata", "QuantData did not return an authoritative value")
    for kind in ("developing_poc", "vah", "val", "prev_poc", "composite_poc", "composite_vah", "composite_val"):
        add_level(kind, "apex_volume_profile", "Profile history is not yet persisted for this field")

    em = structured.get("expected_move") or {}
    for key in ("one_sigma", "upper", "lower", "confidence"):
        val = em.get(key)
        reg.put(f"expected_move_{key}", val if _present(val) else None,
                source="polygon_options", confidence=1.0 if _present(val) else 0.0,
                reason=options_feed.get("error") or "ATM call/put quote or IV was unavailable")

    for provider, configured in provider_flags.items():
        reg.put(f"provider_{provider}_configured", bool(configured), source="configuration",
                confidence=1.0, reason=None)
    reg.put("options_contracts", (options_feed.get("call_contracts", 0) + options_feed.get("put_contracts", 0)) or None,
            source="polygon_options", reason=options_feed.get("error") or "No normalized option contracts")
    reg.put("gamma_regime", structured.get("gamma_regime"), source="quantdata",
            reason="Gamma regime unavailable")
    return reg

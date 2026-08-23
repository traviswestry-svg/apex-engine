"""APEX 68.7.0 — Market Microstructure Intelligence foundation.

Observation-only normalization and interpretation of exchange order-book / trade
microstructure.  This module intentionally does *not* fetch a provider, alter a
trade decision, submit an order, or synthesize missing depth/MBO evidence.

The production APEX baseline currently has ES/MES aggregate-bar access through
its Massive/Polygon futures adapter. Aggregate bars are useful context but are
not equivalent to L2/DOM/MBO and therefore cannot truthfully produce resting
liquidity, add/pull, iceberg, or true aggressor-side CVD evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from typing import Any, Iterable, Mapping, Sequence

VERSION = "68.7.0"
SCHEMA_VERSION = "apex.market_microstructure.v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _levels(rows: Any, *, descending: bool) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        return out
    for row in rows:
        if isinstance(row, Mapping):
            p = _f(row.get("price"))
            q = _f(row.get("size", row.get("qty", row.get("quantity"))))
        elif isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)) and len(row) >= 2:
            p, q = _f(row[0]), _f(row[1])
        else:
            continue
        if p is None or q is None or q < 0:
            continue
        out.append({"price": p, "size": q})
    out.sort(key=lambda x: x["price"], reverse=descending)
    return out


def capability_audit(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Truthful audit of the adapters present in this repository.

    This reports *code capability*, not commercial entitlement. A configured
    POLYGON_API_KEY can enable the existing futures aggregate adapter, but this
    repository contains no native ES L2/MBO order-book adapter.
    """
    env = env or os.environ
    polygon_configured = bool(str(env.get("POLYGON_API_KEY", "")).strip())
    return {
        "ok": True,
        "status": "FOUNDATION_READY_FEED_REQUIRED",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "as_of": _now(),
        "target_instrument": "ES",
        "spx_role": "THESIS_AND_OPTIONS_CONTEXT",
        "es_role": "MICROSTRUCTURE_EXECUTION_CONFIRMATION",
        "current_repository_capabilities": {
            "massive_polygon_futures_aggregate_bars": True,
            "massive_polygon_api_key_configured": polygon_configured,
            "es_mes_front_month_aggregate_probe": True,
            "resting_l2_depth": False,
            "market_by_order_mbo": False,
            "order_add_cancel_modify_events": False,
            "exchange_sequence_ids": False,
            "aggressor_classified_tick_trades": False,
            "true_order_book_heatmap": False,
            "true_cvd": False,
            "native_iceberg_detection": False,
        },
        "what_can_be_built_from_current_feed": [
            "ES price/structure context",
            "aggregate volume context",
            "bar-based proxy analytics explicitly labeled as proxy",
        ],
        "what_requires_new_depth_feed": [
            "resting bid/ask liquidity",
            "historical liquidity heatmap",
            "liquidity add/pull/replenishment",
            "true aggressor-side delta and CVD",
            "DOM imbalance",
            "MBO iceberg reconstruction",
            "stop-run/order-book interaction evidence",
        ],
        "required_normalized_feed_contract": {
            "depth": "timestamp, instrument, side, price, size; preferably order_id + action + exchange_sequence",
            "trades": "timestamp, instrument, price, size, aggressor_side; trade_id/sequence strongly preferred",
            "minimum_for_l2": ["depth snapshots or incremental L2 updates", "aggressor-classified trades"],
            "minimum_for_mbo_icebergs": ["order_id", "add/modify/cancel/execute events", "exchange ordering/sequence"],
        },
        "governance": {
            "production_effect": "NONE",
            "influences_decision": False,
            "execution_authority": False,
            "fabricates_missing_microstructure": False,
            "bars_are_not_labeled_as_dom": True,
        },
    }


def _book_changes(current: list[dict[str, float]], previous: list[dict[str, float]]) -> dict[str, Any]:
    cur = {x["price"]: x["size"] for x in current}
    prev = {x["price"]: x["size"] for x in previous}
    added = pulled = 0.0
    levels_added = levels_pulled = 0
    for price in set(cur) | set(prev):
        change = cur.get(price, 0.0) - prev.get(price, 0.0)
        if change > 0:
            added += change
            levels_added += 1
        elif change < 0:
            pulled += -change
            levels_pulled += 1
    return {
        "added_size": round(added, 4),
        "pulled_size": round(pulled, 4),
        "net_change": round(added - pulled, 4),
        "levels_added": levels_added,
        "levels_pulled": levels_pulled,
        "available": bool(previous),
    }


def _trade_stats(trades: Any) -> dict[str, Any]:
    buy = sell = unknown = 0.0
    count = 0
    if not isinstance(trades, Sequence) or isinstance(trades, (str, bytes, bytearray)):
        trades = []
    for row in trades:
        if not isinstance(row, Mapping):
            continue
        size = _f(row.get("size", row.get("qty", row.get("quantity"))), 0.0) or 0.0
        side = str(row.get("aggressor_side", row.get("side", ""))).upper()
        if side in {"BUY", "B", "ASK", "AT_ASK"}:
            buy += size
        elif side in {"SELL", "S", "BID", "AT_BID"}:
            sell += size
        else:
            unknown += size
        count += 1
    classified = buy + sell
    return {
        "trade_count": count,
        "aggressive_buy_volume": round(buy, 4),
        "aggressive_sell_volume": round(sell, 4),
        "unknown_side_volume": round(unknown, 4),
        "delta": round(buy - sell, 4) if classified else None,
        "classified_volume": round(classified, 4),
        "true_delta_available": classified > 0 and unknown == 0,
    }


def analyze(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    """Analyze one already-normalized microstructure observation.

    Accepted input is deliberately provider-neutral. Missing fields stay missing;
    no proxy is silently promoted to exchange-depth evidence.
    """
    snapshot = snapshot or {}
    instrument = str(snapshot.get("instrument") or "ES").upper()
    source = str(snapshot.get("source") or "UNSPECIFIED")
    book = snapshot.get("book") if isinstance(snapshot.get("book"), Mapping) else {}
    prior = snapshot.get("previous_book") if isinstance(snapshot.get("previous_book"), Mapping) else {}
    bids = _levels(book.get("bids", []), descending=True)
    asks = _levels(book.get("asks", []), descending=False)
    prev_bids = _levels(prior.get("bids", []), descending=True)
    prev_asks = _levels(prior.get("asks", []), descending=False)

    best_bid = bids[0] if bids else None
    best_ask = asks[0] if asks else None
    spread = None
    if best_bid and best_ask:
        spread = round(best_ask["price"] - best_bid["price"], 6)

    bid_depth = sum(x["size"] for x in bids)
    ask_depth = sum(x["size"] for x in asks)
    total_depth = bid_depth + ask_depth
    imbalance = round((bid_depth - ask_depth) / total_depth, 4) if total_depth else None

    bid_changes = _book_changes(bids, prev_bids)
    ask_changes = _book_changes(asks, prev_asks)
    trades = _trade_stats(snapshot.get("trades"))

    response = _f(snapshot.get("price_change"))
    tick_size = _f(snapshot.get("tick_size"), 0.25) or 0.25
    delta = trades.get("delta")
    absorption = {"detected": False, "side": None, "reason": None, "eligible": False}
    if delta is not None and response is not None and trades.get("true_delta_available"):
        absorption["eligible"] = True
        # Large directional execution with <=1 tick progress is a conservative
        # candidate only. Calibration/persistence can mature this later.
        if delta > 0 and response <= tick_size:
            absorption.update(detected=True, side="ASK_SELLER", reason="positive aggressive delta with <=1 tick upward response")
        elif delta < 0 and response >= -tick_size:
            absorption.update(detected=True, side="BID_BUYER", reason="negative aggressive delta with <=1 tick downward response")

    events = snapshot.get("order_events") if isinstance(snapshot.get("order_events"), Sequence) else []
    replenishments: dict[tuple[str, float], int] = {}
    for event in events:
        if not isinstance(event, Mapping):
            continue
        if str(event.get("action") or "").upper() not in {"REPLENISH", "REFILL"}:
            continue
        p = _f(event.get("price"))
        side = str(event.get("side") or "").upper()
        if p is None or side not in {"BID", "ASK"}:
            continue
        key = (side, p)
        replenishments[key] = replenishments.get(key, 0) + 1
    iceberg_candidates = [
        {"side": side, "price": price, "replenishments": n, "classification": "ICEBERG_CANDIDATE"}
        for (side, price), n in sorted(replenishments.items()) if n >= 3
    ]

    l2_available = bool(bids and asks)
    prior_available = bool(prev_bids or prev_asks)
    mbo_available = any(isinstance(e, Mapping) and e.get("order_id") for e in events)
    status = "READY" if l2_available else "FEED_REQUIRED"

    return {
        "ok": True,
        "status": status,
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "observed_at": str(snapshot.get("observed_at") or _now()),
        "instrument": instrument,
        "source": source,
        "book": {
            "l2_available": l2_available,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": spread,
            "bid_depth": round(bid_depth, 4) if l2_available else None,
            "ask_depth": round(ask_depth, 4) if l2_available else None,
            "depth_imbalance": imbalance,
            "levels": {"bids": len(bids), "asks": len(asks)},
        },
        "liquidity_change": {
            "available": prior_available and l2_available,
            "bid": bid_changes,
            "ask": ask_changes,
        },
        "execution": trades,
        "interaction": {
            "absorption_candidate": absorption,
            "iceberg_candidates": iceberg_candidates,
            "mbo_available": bool(mbo_available),
            "iceberg_detection_authoritative": bool(mbo_available and events),
        },
        "microstructure_confirmation": {
            "eligible": bool(l2_available and trades.get("true_delta_available")),
            "score": None,
            "reason": "Calibration required before microstructure can change decision confidence.",
        },
        "governance": {
            "production_effect": "NONE",
            "influences_decision": False,
            "execution_authority": False,
            "advisory_only": True,
            "missing_depth_is_not_synthesized": True,
        },
    }

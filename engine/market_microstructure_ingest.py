"""APEX 68.8.0 — validated L2/MBO ingestion boundary."""
from __future__ import annotations

from typing import Any, Mapping

from .market_microstructure import analyze
from .market_microstructure_store import MicrostructureStore

VERSION = "68.8.0"
ALLOWED_FEED_QUALITY = {"L2", "MBO"}


class MicrostructureValidationError(ValueError):
    pass


def validate_observation(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise MicrostructureValidationError("JSON object required")
    out = dict(payload)
    instrument = str(out.get("instrument") or "ES").upper()
    if instrument not in {"ES", "MES"}:
        raise MicrostructureValidationError("68.8 microstructure ingestion accepts ES or MES only")
    quality = str(out.get("feed_quality") or "").upper()
    if quality not in ALLOWED_FEED_QUALITY:
        raise MicrostructureValidationError("feed_quality must be L2 or MBO; aggregate bars/proxies are rejected")
    source = str(out.get("source") or "").strip()
    if not source or source.upper() in {"UNSPECIFIED", "AGGREGATE", "BARS", "POLYGON_AGGS", "MASSIVE_AGGS"}:
        raise MicrostructureValidationError("a concrete licensed depth-feed source name is required")
    book = out.get("book")
    if not isinstance(book, Mapping) or not isinstance(book.get("bids"), list) or not isinstance(book.get("asks"), list):
        raise MicrostructureValidationError("book.bids and book.asks arrays are required")
    if not book.get("bids") or not book.get("asks"):
        raise MicrostructureValidationError("non-empty bid and ask depth are required")
    if quality == "MBO":
        events = out.get("order_events")
        if events is not None and not isinstance(events, list):
            raise MicrostructureValidationError("MBO order_events must be an array when provided")
    out["instrument"] = instrument
    out["feed_quality"] = quality
    out["source"] = source
    return out


def ingest(payload: Mapping[str, Any] | None, store: MicrostructureStore | None = None) -> dict[str, Any]:
    store = store or MicrostructureStore()
    normalized = validate_observation(payload)
    previous = store.latest_payload(normalized["instrument"])
    if previous and "previous_book" not in normalized:
        previous_book = previous.get("book") if isinstance(previous.get("book"), Mapping) else None
        if previous_book:
            normalized["previous_book"] = previous_book
    result = analyze(normalized)
    if result.get("status") != "READY":
        raise MicrostructureValidationError("depth observation did not normalize to READY")
    row_id = store.append(normalized, result)
    cvd = store.rolling_cvd(normalized["instrument"], limit=600)
    result = dict(result)
    result["version"] = VERSION
    result["persistence"] = {
        "stored": True,
        "row_id": row_id,
        "previous_book_attached": bool(previous),
        "rolling_cvd": {k: v for k, v in cvd.items() if k != "points"},
    }
    return result

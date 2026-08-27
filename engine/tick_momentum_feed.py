"""APEX 69.5.2 — futures trade entitlement & response diagnostics closure.

Consumes genuine individual futures trades from the configured Massive/Polygon
Futures REST trades endpoint and feeds them into the observational 69.5 tick
momentum model. Aggregate bars are never accepted as a substitute.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from .tick_momentum import process_transactions, validate_transactions
from .tick_momentum_store import TickMomentumStore

VERSION = "69.5.2"
SCHEMA_VERSION = "apex.tick_momentum.feed.v1"
SOURCE = "MASSIVE_POLYGON_FUTURES_TRADES"
DEFAULT_LIMIT = 5000
BOOTSTRAP_LIMIT = 2000
MAX_INCREMENTAL_PAGES = 4
MAX_LIVE_LAG_SECONDS = 120.0


def _ns_to_iso(value: Any) -> str:
    try:
        ns = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("futures trade timestamp must be integer nanoseconds") from exc
    if ns <= 0:
        raise ValueError("futures trade timestamp must be positive")
    return datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc).isoformat()


def _trade_key(row: Mapping[str, Any]) -> tuple[int, int, int]:
    return (
        int(row.get("timestamp") or 0),
        int(row.get("sequence_number") or 0),
        int(row.get("report_sequence") or 0),
    )


def normalize_provider_results(payload: Mapping[str, Any] | None, *, instrument: str = "ES") -> list[dict[str, Any]]:
    """Normalize Massive/Polygon futures trade rows into the 69.5 contract.

    No OHLC aggregate representation is accepted here. A malformed provider row
    is skipped; a payload that has no valid individual trades returns an empty
    list instead of fabricating transaction evidence.
    """
    if not isinstance(payload, Mapping):
        return []
    rows = payload.get("results") or payload.get("data") or []
    if not isinstance(rows, list):
        return []
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if any(k in row for k in ("open", "high", "low", "close", "window_start", "resolution")):
            continue
        try:
            price = float(row.get("price"))
            size = float(row.get("size"))
            ns = int(row.get("timestamp"))
        except (TypeError, ValueError):
            continue
        if price <= 0 or size <= 0 or ns <= 0:
            continue
        normalized.append({
            "price": price,
            "size": size,
            "observed_at": _ns_to_iso(ns),
            "provider_timestamp_ns": ns,
            "sequence_number": int(row.get("sequence_number") or 0),
            "report_sequence": int(row.get("report_sequence") or 0),
            "provider_ticker": str(row.get("ticker") or ""),
            "instrument": instrument.upper(),
        })
    normalized.sort(key=lambda x: (
        int(x["provider_timestamp_ns"]),
        int(x["sequence_number"]),
        int(x["report_sequence"]),
    ))
    return normalized


def _cursor_key(feed: Mapping[str, Any] | None) -> tuple[int, int, int]:
    feed = feed or {}
    return (
        int(feed.get("provider_timestamp_ns") or 0),
        int(feed.get("sequence_number") or 0),
        int(feed.get("report_sequence") or 0),
    )


def _safe_next_url(url: Any, configured_base_url: str) -> str | None:
    text = str(url or "").strip()
    if not text:
        return None
    try:
        candidate = urlparse(text)
        configured = urlparse(configured_base_url)
    except Exception:
        return None
    # Never follow pagination off the configured provider host.
    if candidate.scheme not in {"https", "http"} or candidate.netloc != configured.netloc:
        return None
    return text


def _unwrap_provider_response(result: Any) -> tuple[Mapping[str, Any] | None, dict[str, Any]]:
    """Accept legacy JSON mappings or the 69.5.2 diagnostic transport envelope."""
    if isinstance(result, Mapping) and result.get("__apex_provider_response__") is True:
        payload = result.get("payload")
        diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), Mapping) else {}
        return (payload if isinstance(payload, Mapping) else None, dict(diagnostics))
    return (result if isinstance(result, Mapping) else None, {})


def _entitlement_state(diag: Mapping[str, Any], payload: Mapping[str, Any] | None) -> str:
    status = diag.get("provider_http_status")
    try:
        status_i = int(status) if status is not None else None
    except (TypeError, ValueError):
        status_i = None
    if status_i == 401:
        return "AUTHENTICATION_FAILED"
    if status_i == 403:
        return "NOT_ENTITLED_OR_FORBIDDEN"
    if status_i == 404:
        return "ENDPOINT_OR_CONTRACT_NOT_FOUND"
    if status_i == 429:
        return "RATE_LIMITED"
    if status_i is not None and status_i >= 500:
        return "PROVIDER_ERROR"
    if status_i is not None and 200 <= status_i < 300 and isinstance(payload, Mapping):
        return "ACCESS_CONFIRMED"
    if diag.get("provider_response_kind") == "TRANSPORT_ERROR":
        return "TRANSPORT_ERROR"
    return "UNKNOWN"


def _diagnostic_feed_fields(diag: Mapping[str, Any], payload: Mapping[str, Any] | None, credential_source: str) -> dict[str, Any]:
    allowed = (
        "provider_http_status", "provider_content_type", "provider_response_bytes",
        "provider_response_kind", "provider_json_parse_error", "provider_error_code",
        "provider_error_message", "provider_request_host",
    )
    out = {k: diag.get(k) for k in allowed}
    out["credential_source"] = credential_source or "UNKNOWN"
    out["entitlement_state"] = _entitlement_state(diag, payload)
    out["api_key_exposed"] = False
    return out


def poll_futures_trades(
    get_json: Callable[..., Mapping[str, Any] | None],
    *,
    base_url: str,
    api_key: str,
    ticker: str,
    instrument: str = "ES",
    store: TickMomentumStore | None = None,
    limit: int = DEFAULT_LIMIT,
    max_pages: int = MAX_INCREMENTAL_PAGES,
    credential_source: str = "UNKNOWN",
) -> dict[str, Any]:
    """Poll the configured individual-trades endpoint once and persist state.

    Cursoring is based on provider nanosecond timestamp + sequence metadata. The
    provider query deliberately overlaps the cursor timestamp (``timestamp.gte``)
    and local filtering removes duplicates, preventing both double-counting and
    loss of multiple trades sharing the same exchange timestamp.
    """
    store = store or TickMomentumStore()
    state = store.load_state(instrument)
    prior_feed = state.get("feed") if isinstance(state.get("feed"), Mapping) else {}
    cursor = _cursor_key(prior_feed)
    bootstrap = cursor[0] <= 0
    base = str(base_url or "").rstrip("/")
    if not base or not api_key or not ticker:
        feed = {
            **dict(prior_feed),
            "schema_version": SCHEMA_VERSION,
            "version": VERSION,
            "source": SOURCE,
            "status": "NOT_CONFIGURED",
            "ticker": ticker or None,
            "last_error": "MASSIVE/POLYGON futures trade credentials or ticker unavailable",
        }
        state["feed"] = feed
        store.save(state, [])
        return {"ok": False, **feed, "transactions_accepted": 0, "buckets_closed": 0}

    endpoint = f"{base}/futures/v1/trades/{ticker}"
    params: dict[str, Any] = {
        "limit": min(max(int(BOOTSTRAP_LIMIT if bootstrap else limit), 1), 50000),
        "sort": "timestamp.desc" if bootstrap else "timestamp.asc",
        "apiKey": api_key,
    }
    if not bootstrap:
        params["timestamp.gte"] = cursor[0]

    raw_response = get_json(endpoint, params=params, timeout=15)
    payload, provider_diag = _unwrap_provider_response(raw_response)
    diagnostic_fields = _diagnostic_feed_fields(provider_diag, payload, credential_source)
    http_status = provider_diag.get("provider_http_status")
    try:
        http_failed = http_status is not None and not (200 <= int(http_status) < 300)
    except (TypeError, ValueError):
        http_failed = False
    if http_failed or not isinstance(payload, Mapping):
        feed = {
            **dict(prior_feed),
            "schema_version": SCHEMA_VERSION,
            "version": VERSION,
            "source": SOURCE,
            "status": "PROVIDER_UNAVAILABLE_OR_NOT_ENTITLED",
            "ticker": ticker,
            "endpoint": "/futures/v1/trades/{ticker}",
            "last_error": "provider request returned no usable JSON",
            **diagnostic_fields,
        }
        state["feed"] = feed
        store.save(state, [])
        return {"ok": False, **feed, "transactions_accepted": 0, "buckets_closed": 0}

    provider_rows: list[dict[str, Any]] = []
    pages = 0
    current = payload
    while True:
        pages += 1
        provider_rows.extend(normalize_provider_results(current, instrument=instrument))
        if bootstrap or pages >= max(1, int(max_pages)):
            break
        next_url = _safe_next_url(current.get("next_url"), base)
        if not next_url:
            break
        next_raw = get_json(next_url, params={"apiKey": api_key}, timeout=15)
        current, _next_diag = _unwrap_provider_response(next_raw)
        if not isinstance(current, Mapping):
            break

    fresh = [r for r in provider_rows if (
        int(r["provider_timestamp_ns"]), int(r["sequence_number"]), int(r["report_sequence"])
    ) > cursor]
    # De-duplicate provider overlap/pagination locally before model validation.
    unique: dict[tuple[int, int, int], dict[str, Any]] = {}
    for row in fresh:
        unique[(int(row["provider_timestamp_ns"]), int(row["sequence_number"]), int(row["report_sequence"]))] = row
    fresh = [unique[k] for k in sorted(unique)]

    if fresh:
        last = fresh[-1]
        newest_dt = datetime.fromisoformat(str(last["observed_at"]))
        lag_seconds = max(0.0, (datetime.now(timezone.utc) - newest_dt).total_seconds())
        # A delayed futures entitlement must never masquerade as live tick
        # momentum. Advance the provider cursor for observability/dedup, but do
        # not feed stale transactions into the current multi-horizon state.
        if lag_seconds > MAX_LIVE_LAG_SECONDS:
            feed = {
                **dict(prior_feed),
                "schema_version": SCHEMA_VERSION,
                "version": VERSION,
                "source": SOURCE,
                "status": "STALE_TRANSACTION_FEED",
                **diagnostic_fields,
                "ticker": ticker,
                "endpoint": "/futures/v1/trades/{ticker}",
                "provider_timestamp_ns": int(last["provider_timestamp_ns"]),
                "sequence_number": int(last["sequence_number"]),
                "report_sequence": int(last["report_sequence"]),
                "last_provider_trade_at": last["observed_at"],
                "provider_lag_seconds": round(lag_seconds, 3),
                "max_live_lag_seconds": MAX_LIVE_LAG_SECONDS,
                "last_success_at": datetime.now(timezone.utc).isoformat(),
                "last_error": None,
                "polls": int(prior_feed.get("polls") or 0) + 1,
                "last_batch_transactions": 0,
                "stale_provider_rows_seen": int(prior_feed.get("stale_provider_rows_seen") or 0) + len(fresh),
                "pages_read": pages,
                "bootstrap": bootstrap,
            }
            state["feed"] = feed
            store.save(state, [])
            return {"ok": True, **feed, "transactions_accepted": 0, "buckets_closed": 0}

        validated = validate_transactions(
            [{"price": r["price"], "size": r["size"], "observed_at": r["observed_at"]} for r in fresh],
            instrument=instrument,
        )
        after, closed = process_transactions(state, validated, instrument=instrument)
        feed = {
            **dict(prior_feed),
            "schema_version": SCHEMA_VERSION,
            "version": VERSION,
            "source": SOURCE,
            "status": "OBSERVING",
                **diagnostic_fields,
            "ticker": ticker,
            "endpoint": "/futures/v1/trades/{ticker}",
            "provider_timestamp_ns": int(last["provider_timestamp_ns"]),
            "sequence_number": int(last["sequence_number"]),
            "report_sequence": int(last["report_sequence"]),
            "last_provider_trade_at": last["observed_at"],
            "provider_lag_seconds": round(lag_seconds, 3),
            "max_live_lag_seconds": MAX_LIVE_LAG_SECONDS,
            "last_success_at": datetime.now(timezone.utc).isoformat(),
            "last_error": None,
            "polls": int(prior_feed.get("polls") or 0) + 1,
            "transactions_accepted_total": int(prior_feed.get("transactions_accepted_total") or 0) + len(validated),
            "last_batch_transactions": len(validated),
            "pages_read": pages,
            "bootstrap": bootstrap,
        }
        after["feed"] = feed
        store.save(after, closed)
        return {"ok": True, **feed, "transactions_accepted": len(validated), "buckets_closed": len(closed), "alignment": after.get("alignment")}

    feed = {
        **dict(prior_feed),
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "source": SOURCE,
        "status": "NO_NEW_TRANSACTIONS",
        **diagnostic_fields,
        "ticker": ticker,
        "endpoint": "/futures/v1/trades/{ticker}",
        "last_success_at": datetime.now(timezone.utc).isoformat(),
        "last_error": None,
        "polls": int(prior_feed.get("polls") or 0) + 1,
        "last_batch_transactions": 0,
        "pages_read": pages,
        "bootstrap": bootstrap,
    }
    state["feed"] = feed
    store.save(state, [])
    return {"ok": True, **feed, "transactions_accepted": 0, "buckets_closed": 0}

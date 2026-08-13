"""APEX 16.9.2 broker integration completion diagnostics.

Read-only certification of the E*TRADE/market-data path used by the Trade Command
Center. It never submits, previews, changes, or cancels an order.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

VERSION = "16.9.2_BROKER_INTEGRATION_COMPLETION"


def _state(ok: Optional[bool]) -> str:
    if ok is True:
        return "PASS"
    if ok is False:
        return "FAIL"
    return "NOT_TESTED"


def _available(rows: List[Dict[str, Any]], key: str) -> int:
    return sum(1 for row in rows if row.get(key) not in (None, ""))


def assess_chain(contracts: List[Dict[str, Any]], source: Optional[str] = None,
                 latency_ms: Optional[float] = None) -> Dict[str, Any]:
    rows = list(contracts or [])
    n = len(rows)
    two_sided = sum(1 for r in rows if r.get("bid") is not None and r.get("ask") is not None)
    greeks = sum(1 for r in rows if any(r.get(k) is not None for k in ("delta", "gamma", "theta", "vega")))
    iv = _available(rows, "iv")
    quote_ok = n > 0 and two_sided > 0
    return {
        "source": source,
        "contracts": n,
        "two_sided_quotes": two_sided,
        "quote_coverage_pct": round(two_sided / n * 100.0, 1) if n else 0.0,
        "greeks_contracts": greeks,
        "greeks_coverage_pct": round(greeks / n * 100.0, 1) if n else 0.0,
        "iv_contracts": iv,
        "iv_coverage_pct": round(iv / n * 100.0, 1) if n else 0.0,
        "volume_contracts": _available(rows, "volume"),
        "open_interest_contracts": _available(rows, "open_interest"),
        "latency_ms": latency_ms,
        "quotes_state": _state(quote_ok),
        "greeks_state": _state(greeks > 0 if n else None),
        "chain_state": _state(n > 0),
    }


def build_diagnostics(*, adapter: Any, chain_fetcher: Optional[Callable[[str, str, str], Dict[str, Any]]] = None,
                      expiration: str = "", side: str = "CALL") -> Dict[str, Any]:
    status = adapter.status()
    configured = bool((status.data or {}).get("configured"))
    account_test = None
    account_count = 0
    account_error: List[str] = []
    if configured:
        accounts = adapter.list_accounts()
        account_test = accounts.ok
        account_count = len(((accounts.data or {}).get("accounts") or []))
        account_error = list(accounts.errors or [])

    chain_result: Dict[str, Any] = {}
    if chain_fetcher and expiration:
        chain_result = chain_fetcher("SPX", expiration, side) or {}
    chain = assess_chain(chain_result.get("contracts") or [], chain_result.get("source"),
                         chain_result.get("latency_ms"))

    checks = {
        "oauth": _state(configured),
        "accounts": _state(account_test),
        "account_count": account_count,
        "option_chain": chain["chain_state"],
        "quotes": chain["quotes_state"],
        "greeks": chain["greeks_state"],
        "preview": "NOT_TESTED",
        "execution": "BLOCKED" if not adapter.trading_enabled else "CONFIRMATION_GATED",
    }
    return {
        "version": VERSION,
        "broker": "etrade",
        "environment": adapter.mode,
        "checks": checks,
        "chain": chain,
        "errors": account_error + list(chain_result.get("warnings") or []),
        "safety": {
            "read_only_diagnostics": True,
            "automatic_execution_enabled": False,
            "trading_enabled": bool(adapter.trading_enabled),
        },
    }

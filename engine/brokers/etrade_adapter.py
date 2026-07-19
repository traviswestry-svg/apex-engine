"""engine/brokers/etrade_adapter.py — E*TRADE (sandbox-first) broker adapter.

Implements BrokerInterface for E*TRADE. OAuth 1.0a request signing is done with the
standard library (HMAC-SHA1) so no extra dependency is required; the signing routine
is validated against the canonical OAuth test vector in tests/test_trade_command.py.

Safety: defaults to the sandbox base URL. Trading is gated by ETRADE_ENABLE_TRADING;
when false, preview still works but place_* refuse. Credentials come only from env —
nothing is hardcoded, and the adapter reports `configured=False` when keys are absent
rather than raising, so the rest of APEX is unaffected.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import os
import time
import urllib.parse as up
import uuid
from typing import Any, Dict, List, Optional

import requests

from engine.execution.broker_interface import (
    BrokerInterface, BrokerResult, OrderIntent, ChangeIntent,
)
from engine.options.options_data_bus import normalize_chain

_SANDBOX_BASE = "https://apisb.etrade.com"
_PROD_BASE = "https://api.etrade.com"


def _pct(s: Any) -> str:
    """RFC 3986 percent-encoding as required by OAuth 1.0a."""
    return up.quote(str(s), safe="~")


def oauth1_signature_base_string(method: str, url: str, params: Dict[str, str]) -> str:
    """Build the OAuth 1.0a signature base string (public for testing)."""
    norm = "&".join(f"{_pct(k)}={_pct(v)}" for k, v in sorted(params.items()))
    return "&".join([method.upper(), _pct(url), _pct(norm)])


def oauth1_sign(method: str, url: str, params: Dict[str, str],
                consumer_secret: str, token_secret: str = "") -> str:
    """Return the base64 HMAC-SHA1 OAuth signature for the given request."""
    base = oauth1_signature_base_string(method, url, params)
    key = f"{_pct(consumer_secret)}&{_pct(token_secret)}"
    digest = hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


class ETradeAdapter(BrokerInterface):
    name = "etrade"

    def __init__(self) -> None:
        self.env = os.getenv("ETRADE_ENV", "sandbox").strip().lower()
        self.mode = "sandbox" if self.env != "production" else "production"
        self.base = _SANDBOX_BASE if self.mode == "sandbox" else _PROD_BASE
        self.consumer_key = os.getenv("ETRADE_CONSUMER_KEY", "").strip()
        self.consumer_secret = os.getenv("ETRADE_CONSUMER_SECRET", "").strip()
        self.oauth_token = os.getenv("ETRADE_OAUTH_TOKEN", "").strip()
        self.oauth_token_secret = os.getenv("ETRADE_OAUTH_TOKEN_SECRET", "").strip()
        self.account_id_key = os.getenv("ETRADE_ACCOUNT_ID_KEY", "").strip()
        self.trading_enabled = os.getenv("ETRADE_ENABLE_TRADING", "false").strip().lower() == "true"
        self.timeout = float(os.getenv("ETRADE_HTTP_TIMEOUT", "12"))

    # ── config / auth ──────────────────────────────────────────────────────
    @property
    def configured(self) -> bool:
        return bool(self.consumer_key and self.consumer_secret and
                    self.oauth_token and self.oauth_token_secret)

    def _auth_header(self, method: str, url: str, extra: Optional[Dict[str, str]] = None) -> str:
        oauth = {
            "oauth_consumer_key": self.consumer_key,
            "oauth_nonce": uuid.uuid4().hex,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_token": self.oauth_token,
            "oauth_version": "1.0",
        }
        all_params = dict(oauth)
        if extra:
            all_params.update(extra)
        sig = oauth1_sign(method, url, all_params, self.consumer_secret, self.oauth_token_secret)
        oauth["oauth_signature"] = sig
        header = "OAuth " + ", ".join(f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(oauth.items()))
        return header

    def _request(self, method: str, path: str, *, params: Optional[Dict[str, str]] = None,
                 json_body: Optional[Dict[str, Any]] = None) -> BrokerResult:
        if not self.configured:
            return BrokerResult(ok=False, mode=self.mode,
                                errors=["E*TRADE not configured — set ETRADE_* env vars."])
        url = self.base + path
        query = params or {}
        try:
            headers = {"Authorization": self._auth_header(method, url, query if method == "GET" else None),
                       "Accept": "application/json"}
            if json_body is not None:
                headers["Content-Type"] = "application/json"
            resp = requests.request(method, url, headers=headers, params=query,
                                    json=json_body, timeout=self.timeout)
            ct = resp.headers.get("content-type", "")
            data = resp.json() if "json" in ct else {"raw": resp.text}
            if resp.status_code >= 400:
                return BrokerResult(ok=False, mode=self.mode, data=data,
                                    errors=[f"E*TRADE {resp.status_code}"])
            return BrokerResult(ok=True, mode=self.mode, data=data)
        except Exception as e:
            return BrokerResult(ok=False, mode=self.mode, errors=[f"request failed: {e}"])

    # ── interface methods ──────────────────────────────────────────────────
    def status(self) -> BrokerResult:
        return BrokerResult(ok=True, mode=self.mode, data={
            "broker": "etrade", "env": self.env, "base_url": self.base,
            "configured": self.configured, "trading_enabled": self.trading_enabled,
            "account_id_key_set": bool(self.account_id_key),
        })

    def list_accounts(self) -> BrokerResult:
        r = self._request("GET", "/v1/accounts/list.json")
        if not r.ok:
            return r
        accts = (((r.data or {}).get("AccountListResponse") or {}).get("Accounts") or {}).get("Account") or []
        norm = [{
            "account_id_key": a.get("accountIdKey"),
            "account_id": a.get("accountId"),
            "type": a.get("accountType"),
            "description": a.get("accountDesc"),
            "status": a.get("accountStatus"),
        } for a in accts]
        return BrokerResult(ok=True, mode=self.mode, data={"accounts": norm})

    def get_positions(self, account_id_key: str) -> BrokerResult:
        key = account_id_key or self.account_id_key
        if not key:
            return BrokerResult(ok=False, mode=self.mode, errors=["No account_id_key."])
        r = self._request("GET", f"/v1/accounts/{key}/portfolio.json")
        if not r.ok:
            return r
        positions = (((r.data or {}).get("PortfolioResponse") or {}).get("AccountPortfolio") or [{}])
        out: List[Dict[str, Any]] = []
        for acct in positions:
            for p in acct.get("Position", []) or []:
                prod = p.get("Product", {})
                out.append({
                    "symbol": prod.get("symbol"),
                    "security_type": prod.get("securityType"),
                    "osi_key": prod.get("symbol"),
                    "quantity": p.get("quantity"),
                    "market_value": p.get("marketValue"),
                    "cost_basis": p.get("totalCost"),
                    "side": "LONG" if (p.get("quantity") or 0) >= 0 else "SHORT",
                })
        return BrokerResult(ok=True, mode=self.mode, data={"positions": out})

    def get_option_expirations(self, symbol: str = "SPX") -> BrokerResult:
        r = self._request("GET", "/v1/market/optionexpiredate.json", params={"symbol": symbol})
        if not r.ok:
            return r
        dates = (((r.data or {}).get("OptionExpireDateResponse") or {}).get("ExpirationDate") or [])
        out = []
        for d in dates:
            try:
                out.append(f"{int(d['year']):04d}-{int(d['month']):02d}-{int(d['day']):02d}")
            except Exception:
                continue
        return BrokerResult(ok=True, mode=self.mode, data={"expirations": sorted(set(out))})

    def get_option_chain(self, symbol: str, expiration, side: str) -> BrokerResult:
        if isinstance(expiration, str):
            try:
                expiration = dt.date.fromisoformat(expiration)
            except Exception:
                return BrokerResult(ok=False, mode=self.mode, errors=["bad expiration date"])
        params = {
            "symbol": symbol, "expiryYear": str(expiration.year),
            "expiryMonth": str(expiration.month), "expiryDay": str(expiration.day),
            "optionType": "CALL" if side.upper() == "CALL" else "PUT",
            "includeWeekly": "true",
        }
        r = self._request("GET", "/v1/market/optionchains.json", params=params)
        if not r.ok:
            return r
        pairs = (((r.data or {}).get("OptionChainResponse") or {}).get("OptionPair") or [])
        raw: List[Dict[str, Any]] = []
        want = side.upper()
        for pair in pairs:
            leg = pair.get("Call") if want == "CALL" else pair.get("Put")
            if not leg:
                continue
            g = leg.get("OptionGreeks", {})
            raw.append({
                "osiKey": leg.get("osiKey"), "symbol": leg.get("symbol"),
                "strikePrice": leg.get("strikePrice"), "side": want,
                "bid": leg.get("bid"), "ask": leg.get("ask"), "lastPrice": leg.get("lastPrice"),
                "volume": leg.get("volume"), "openInterest": leg.get("openInterest"),
                "expiration": expiration.isoformat(),
                "greeks": {"delta": g.get("delta"), "gamma": g.get("gamma"),
                           "theta": g.get("theta"), "vega": g.get("vega"), "iv": g.get("iv")},
                "quoteTime": leg.get("timeStamp"),
            })
        contracts = [c.to_dict() for c in normalize_chain(raw, symbol=symbol, source="etrade")]
        return BrokerResult(ok=True, mode=self.mode, data={"contracts": contracts})

    # ── orders ─────────────────────────────────────────────────────────────
    def _order_payload(self, intent: OrderIntent, preview: bool, *,
                       preview_id: Optional[str] = None) -> Dict[str, Any]:
        etrade_action = {"BUY_OPEN": "BUY_OPEN", "SELL_CLOSE": "SELL_CLOSE"}.get(intent.action, intent.action)
        instrument = {
            "Product": {"securityType": "OPTN", "symbol": intent.symbol},
            "orderAction": etrade_action,
            "quantityType": "QUANTITY",
            "quantity": intent.quantity,
            "osiKey": intent.osi_key,
        }
        order = {
            "allOrNone": "false",
            "priceType": intent.order_type,   # LIMIT / MARKET / STOP / STOP_LIMIT
            "orderTerm": "GOOD_FOR_DAY" if intent.time_in_force == "DAY" else "GOOD_UNTIL_CANCEL",
            "marketSession": "REGULAR",
            "Instrument": [instrument],
        }
        if intent.limit_price is not None:
            order["limitPrice"] = intent.limit_price
        if intent.stop_price is not None:
            order["stopPrice"] = intent.stop_price
        client_id = uuid.uuid4().hex[:20]
        body: Dict[str, Any] = {
            ("PreviewOrderRequest" if preview else "PlaceOrderRequest"): {
                "orderType": "OPTN",
                "clientOrderId": client_id,
                "Order": [order],
            }
        }
        if not preview and preview_id:
            body["PlaceOrderRequest"]["PreviewIds"] = [{"previewId": preview_id}]
        return body

    def preview_order(self, order_intent: OrderIntent) -> BrokerResult:
        key = self.account_id_key
        if not key:
            return BrokerResult(ok=False, mode=self.mode, errors=["No ETRADE_ACCOUNT_ID_KEY."])
        body = self._order_payload(order_intent, preview=True)
        r = self._request("POST", f"/v1/accounts/{key}/orders/preview.json", json_body=body)
        if r.ok:
            pid = (((r.data or {}).get("PreviewOrderResponse") or {}).get("PreviewIds") or [{}])[0].get("previewId")
            r.data["preview_id"] = pid
        return r

    def place_order(self, preview_id: str, order_intent: OrderIntent) -> BrokerResult:
        if not self.trading_enabled:
            return BrokerResult(ok=False, mode=self.mode,
                                errors=["Order placement blocked — ETRADE_ENABLE_TRADING is not true."])
        key = self.account_id_key
        body = self._order_payload(order_intent, preview=False, preview_id=preview_id)
        return self._request("POST", f"/v1/accounts/{key}/orders/place.json", json_body=body)

    def _complex_order_payload(self, intent, preview: bool, *, preview_id: Optional[str] = None) -> Dict[str, Any]:
        instruments = []
        for leg in intent.legs:
            instruments.append({
                "Product": {"securityType": "OPTN", "symbol": intent.symbol},
                "orderAction": leg.action,
                "quantityType": "QUANTITY",
                "quantity": leg.quantity,
                "osiKey": leg.osi_key,
            })
        order = {
            "allOrNone": "true" if intent.all_or_none else "false",
            "priceType": "NET_CREDIT" if intent.price_effect == "NET_CREDIT" else ("NET_DEBIT" if intent.price_effect == "NET_DEBIT" else "LIMIT"),
            "orderTerm": "GOOD_FOR_DAY" if intent.time_in_force == "DAY" else "GOOD_UNTIL_CANCEL",
            "marketSession": "REGULAR",
            "limitPrice": intent.limit_price,
            "Instrument": instruments,
        }
        root = "PreviewOrderRequest" if preview else "PlaceOrderRequest"
        body = {root: {"orderType": "OPTN", "clientOrderId": uuid.uuid4().hex[:20], "Order": [order]}}
        if not preview and preview_id:
            body[root]["PreviewIds"] = [{"previewId": preview_id}]
        return body

    def preview_complex_order(self, order_intent) -> BrokerResult:
        key = self.account_id_key
        if not key:
            return BrokerResult(ok=False, mode=self.mode, errors=["No ETRADE_ACCOUNT_ID_KEY."])
        r = self._request("POST", f"/v1/accounts/{key}/orders/preview.json", json_body=self._complex_order_payload(order_intent, True))
        if r.ok:
            pid = (((r.data or {}).get("PreviewOrderResponse") or {}).get("PreviewIds") or [{}])[0].get("previewId")
            r.data["preview_id"] = pid
        return r

    def place_complex_order(self, preview_id: str, order_intent) -> BrokerResult:
        if not self.trading_enabled:
            return BrokerResult(ok=False, mode=self.mode, errors=["Order placement blocked — ETRADE_ENABLE_TRADING is not true."])
        key = self.account_id_key
        return self._request("POST", f"/v1/accounts/{key}/orders/place.json", json_body=self._complex_order_payload(order_intent, False, preview_id=preview_id))

    def cancel_order(self, order_id: str) -> BrokerResult:
        key = self.account_id_key
        body = {"CancelOrderRequest": {"orderId": order_id}}
        return self._request("PUT", f"/v1/accounts/{key}/orders/cancel.json", json_body=body)

    def preview_change_order(self, order_id: str, change_intent: ChangeIntent) -> BrokerResult:
        key = self.account_id_key
        order: Dict[str, Any] = {"priceType": "LIMIT", "orderTerm": "GOOD_FOR_DAY", "marketSession": "REGULAR"}
        if change_intent.new_limit_price is not None:
            order["limitPrice"] = change_intent.new_limit_price
        if change_intent.new_stop_price is not None:
            order["priceType"] = "STOP"
            order["stopPrice"] = change_intent.new_stop_price
        body = {"PreviewOrderRequest": {"orderType": "OPTN", "Order": [order]}}
        r = self._request("PUT", f"/v1/accounts/{key}/orders/{order_id}/change/preview.json", json_body=body)
        if r.ok:
            pid = (((r.data or {}).get("PreviewOrderResponse") or {}).get("PreviewIds") or [{}])[0].get("previewId")
            r.data["preview_id"] = pid
        return r

    def place_change_order(self, order_id: str, preview_id: str, change_intent: ChangeIntent) -> BrokerResult:
        if not self.trading_enabled:
            return BrokerResult(ok=False, mode=self.mode,
                                errors=["Change placement blocked — ETRADE_ENABLE_TRADING is not true."])
        key = self.account_id_key
        order: Dict[str, Any] = {"priceType": "LIMIT", "orderTerm": "GOOD_FOR_DAY", "marketSession": "REGULAR"}
        if change_intent.new_limit_price is not None:
            order["limitPrice"] = change_intent.new_limit_price
        if change_intent.new_stop_price is not None:
            order["priceType"] = "STOP"
            order["stopPrice"] = change_intent.new_stop_price
        body = {"PlaceOrderRequest": {"orderType": "OPTN", "PreviewIds": [{"previewId": preview_id}],
                                      "Order": [order]}}
        return self._request("PUT", f"/v1/accounts/{key}/orders/{order_id}/change/place.json", json_body=body)

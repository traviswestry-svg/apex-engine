"""engine/flow_classifier.py — APEX 9 Step 2: Institutional Flow Classifier.

Read-only consumer of the existing normalized flow model (`engine/flow_tape.py`
rows). Classifies each eligible options print. Recomputes nothing upstream and
never mutates provider data — the same contract `premium_strategy` follows.

WHY THIS MODULE EXISTS
----------------------
`flow_tape._classify_row` already produces a shallow label (BUY_SWEEP etc.).
This module does not replace it. It adds the layer the Phase 0 audit found
missing: a classification that separates what was *observed* from what was
*derived* from what is merely *hypothesised*, with explicit confidence and
explicit exclusions.

THE THREE CERTAINTY LAYERS (the core rule — never collapse these)
----------------------------------------------------------------
1. `observable_facts` — copied from the provider. Zero inference. If the
   provider didn't say it, it isn't here.
2. `classification` / `execution_aggression` / `size_class` — deterministic
   rules applied to layer 1. Derived, but mechanical and reproducible.
3. `possible_intents` — hypotheses. Always plural, always with confidence and
   basis, never asserted as fact. `excluded_intents` records what the data
   cannot support.

    Observable fact:      executed above the ask, provider tagged SWEEP
    Derived:              aggressive buy sweep
    Intent hypothesis:    possible directional opening purchase (unconfirmable)

These are stored in separate fields precisely so downstream code cannot treat a
hypothesis with the same certainty as a print.

LANGUAGE RULE
-------------
No label in this module claims confirmed institutional intent. We emit
`likely_roll`, `possible_hedge`, `spread_leg_candidate`,
`directional_interpretation_uncertain`. We never emit `institution_accumulating`,
`smart_money_buying`, or `confirmed_opening_position` — a print shows a
transaction, not a motive, and the counterparty's book is not observable.

WHAT THE DATA SUPPORTS (verified against the live provider payload)
------------------------------------------------------------------
Available per print: ticker · contract_type · strike · expiration · premium ·
trade_price · contracts · trade_side_code (ABOVE_ASK/AT_ASK/MID/AT_BID/
BELOW_BID) · consolidation_type (SWEEP/BLOCK/SPLIT) · time_et.

NOT available per print, and therefore never inferred here:
  * open interest → volume/OI is impossible, so opening vs closing is
    ALWAYS an excluded intent, not a guess.
  * exchange sequence / exchange count → a SWEEP is taken as provider-reported,
    not re-derived from multi-exchange prints.
  * bid/ask quote at trade time, per-print IV, Greeks → no spread-quality or
    IV-contribution claims are made here.

A NOTE ON THE UPSTREAM FALLBACK (deliberately not inherited)
------------------------------------------------------------
`flow_tape._classify_row` falls back to `CALL→BUY, PUT→SELL` when
`trade_side_code` is missing. That is a guess wearing the costume of a fact, and
this classifier does not consume `aggressor_side` because of it. We read
`trade_side_code` directly; when it is absent the aggression is UNKNOWN, the
event is DEGRADED, and no directional claim is made.

DETERMINISM
-----------
`event_id` is a stable hash of the print's identifying fields, so the same input
always yields the same id — a requirement for replay and for clustering (Step 3)
to reference members.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, List, Optional, Tuple

CLASSIFIER_VERSION = "9.2.0_FLOW_CLASSIFIER"

# Feature flag — the classifier is additive and off-switchable.
FLOW_CLASSIFIER_ENABLED = os.getenv("FLOW_CLASSIFIER_ENABLED", "true").lower() == "true"

# ── Structural classifications (layer 2 — derived from provider facts) ──────
SWEEP = "SWEEP"
BLOCK = "BLOCK"
SPLIT = "SPLIT"
SINGLE_LEG = "SINGLE_LEG"
AMBIGUOUS = "AMBIGUOUS"

# ── Size classes (layer 2) ─────────────────────────────────────────────────
INSTITUTIONAL_SIZE = "INSTITUTIONAL_SIZE"
MID_SIZE = "MID_SIZE"
RETAIL_SIZE_NOISE = "RETAIL_SIZE_NOISE"

# ── Execution aggression (layer 2) ─────────────────────────────────────────
AGGRESSIVE_BUY = "AGGRESSIVE_BUY"
BUY = "BUY"
PASSIVE_MID = "PASSIVE_MID"
SELL = "SELL"
AGGRESSIVE_SELL = "AGGRESSIVE_SELL"
UNKNOWN_AGGRESSION = "UNKNOWN"

# ── Intent hypotheses (layer 3 — never facts) ──────────────────────────────
SPREAD_LEG_CANDIDATE = "spread_leg_candidate"
LIKELY_ROLL = "likely_roll"
POSSIBLE_HEDGE = "possible_hedge"
POSSIBLE_OPENING = "possible_opening_transaction"
POSSIBLE_CLOSING = "possible_closing_transaction"
DIRECTIONAL_UNCERTAIN = "directional_interpretation_uncertain"
POSSIBLE_DIRECTIONAL = "possible_directional_position"
POSSIBLE_VOLATILITY_TRADE = "possible_volatility_trade"

# ── Data quality (spec §2.4 vocabulary, scoped to a print) ─────────────────
COMPLETE = "COMPLETE"
PARTIAL = "PARTIAL"
DEGRADED = "DEGRADED"

# Provider execution codes → aggression. Read directly; no contract_type fallback.
_SIDE_CODE_AGGRESSION: Dict[str, str] = {
    "ABOVE_ASK": AGGRESSIVE_BUY,
    "AT_ASK": BUY,
    "MID": PASSIVE_MID,
    "AT_BID": SELL,
    "BELOW_BID": AGGRESSIVE_SELL,
}

_BUY_SIDE = {AGGRESSIVE_BUY, BUY}
_SELL_SIDE = {AGGRESSIVE_SELL, SELL}

_CONSOLIDATION: Dict[str, str] = {"SWEEP": SWEEP, "BLOCK": BLOCK, "SPLIT": SPLIT}

# Tunables (configurable; versioned with the classifier).
_INSTITUTIONAL_PREMIUM = float(os.getenv("FLOW_INSTITUTIONAL_PREMIUM", "250000"))
_RETAIL_PREMIUM = float(os.getenv("FLOW_RETAIL_PREMIUM", "25000"))
_PAIR_WINDOW_S = float(os.getenv("FLOW_PAIR_WINDOW_S", "2"))
_DELAYED_PRINT_S = float(os.getenv("FLOW_DELAYED_PRINT_S", "120"))


def _safe_float(v: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if v is None or v == "":
            return default
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _secs(time_et: Any) -> Optional[int]:
    """'HH:MM:SS' → seconds since midnight ET. None if unparseable.

    The provider gives second resolution with no date, so pairing windows are
    within-session only. Sub-second sequencing is not observable here.
    """
    s = str(time_et or "").strip()
    parts = s.split(":")
    if len(parts) < 2:
        return None
    try:
        h = int(parts[0]); m = int(parts[1])
        sec = int(parts[2]) if len(parts) > 2 else 0
    except (TypeError, ValueError):
        return None
    if not (0 <= h < 24 and 0 <= m < 60 and 0 <= sec < 60):
        return None
    return h * 3600 + m * 60 + sec


def make_event_id(row: Dict[str, Any]) -> str:
    """Deterministic id for a print — same input always yields the same id.

    Hashes only identifying fields (never derived values), so ids remain stable
    across classifier versions and support replay + cluster membership.
    """
    parts = [
        str(row.get("ticker") or ""),
        str(row.get("time_et") or ""),
        str(row.get("contract_type") or ""),
        str(row.get("strike") if row.get("strike") is not None else ""),
        str(row.get("expiration") or ""),
        str(row.get("trade_price") if row.get("trade_price") is not None else ""),
        str(row.get("contracts") if row.get("contracts") is not None else ""),
        str(row.get("premium") if row.get("premium") is not None else ""),
        str(row.get("trade_side_code") or ""),
        str(row.get("consolidation_type") or ""),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _observable_facts(row: Dict[str, Any]) -> Dict[str, Any]:
    """Layer 1 — copied verbatim from the provider. No inference whatsoever."""
    return {
        "ticker": row.get("ticker"),
        "time_et": row.get("time_et"),
        "contract_type": row.get("contract_type"),
        "strike": row.get("strike"),
        "expiration": row.get("expiration"),
        "trade_price": row.get("trade_price"),
        "contracts": row.get("contracts"),
        "premium": row.get("premium"),
        "trade_side_code": row.get("trade_side_code") or None,
        "consolidation_type": row.get("consolidation_type") or None,
        # Explicitly recorded as absent so downstream never assumes silence = zero.
        "open_interest": None,
        "exchange_count": None,
        "quote_at_trade": ({"bid": row.get("bid"), "ask": row.get("ask")}
                           if row.get("bid") is not None or row.get("ask") is not None else None),
        "delta": row.get("delta") if row.get("delta") is not None else None,
        "implied_volatility": None,
    }


def _classify_structure(facts: Dict[str, Any]) -> Tuple[str, float, List[str]]:
    """Layer 2 — structure from the provider's consolidation tag."""
    cons = str(facts.get("consolidation_type") or "").upper()
    if cons in _CONSOLIDATION:
        label = _CONSOLIDATION[cons]
        return label, 0.95, [f"Provider tagged consolidation_type={cons}."]
    if cons:
        return AMBIGUOUS, 0.30, [f"Unrecognised consolidation_type={cons!r}."]
    # No consolidation tag: a lone print. Calling it SINGLE_LEG is a mild
    # inference (the provider may simply not have tagged it), so confidence is
    # moderate, not high.
    return SINGLE_LEG, 0.55, ["No consolidation tag — treated as a single print."]


def _classify_aggression(facts: Dict[str, Any]) -> Tuple[str, List[str], List[str]]:
    """Layer 2 — aggression strictly from trade_side_code. No fallback guessing."""
    code = str(facts.get("trade_side_code") or "").upper()
    if not code:
        return (UNKNOWN_AGGRESSION, [],
                ["trade_side_code missing — execution aggression is not observable; "
                 "no directional interpretation is supported by this print."])
    if code not in _SIDE_CODE_AGGRESSION:
        return (UNKNOWN_AGGRESSION, [],
                [f"Unrecognised trade_side_code={code!r} — aggression not observable."])
    agg = _SIDE_CODE_AGGRESSION[code]
    return agg, [f"Executed {code.replace('_', ' ').lower()}."], []


def _classify_size(facts: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Layer 2 — size class by dollar premium."""
    prem = _safe_float(facts.get("premium"), 0.0) or 0.0
    if prem >= _INSTITUTIONAL_PREMIUM:
        return INSTITUTIONAL_SIZE, [f"Premium ${prem:,.0f} ≥ ${_INSTITUTIONAL_PREMIUM:,.0f}."]
    if prem <= _RETAIL_PREMIUM:
        return RETAIL_SIZE_NOISE, [f"Premium ${prem:,.0f} ≤ ${_RETAIL_PREMIUM:,.0f}."]
    return MID_SIZE, [f"Premium ${prem:,.0f} between retail and institutional thresholds."]


def _directional_lean(contract_type: str, aggression: str) -> Tuple[str, float]:
    """Layer 2/3 boundary — the mechanical lean of the print, not a conviction.

    A bought call leans bullish *as a transaction*. It is not evidence that
    anyone is bullish: it may be a spread leg, a hedge against short stock, or
    an overwrite being closed. Confidence stays deliberately moderate and the
    intent layer carries the alternatives.
    """
    ct = (contract_type or "").upper()
    if aggression == UNKNOWN_AGGRESSION or ct not in ("CALL", "PUT"):
        return "UNCERTAIN", 0.0
    if aggression == PASSIVE_MID:
        # Mid fills don't reveal who initiated — the least informative case.
        return "UNCERTAIN", 0.10
    aggressive = aggression in (AGGRESSIVE_BUY, AGGRESSIVE_SELL)
    conf = 0.60 if aggressive else 0.45
    if ct == "CALL":
        return ("BULLISH", conf) if aggression in _BUY_SIDE else ("BEARISH", conf)
    return ("BEARISH", conf) if aggression in _BUY_SIDE else ("BULLISH", conf)


def _build_pair_index(batch: List[Dict[str, Any]]) -> Dict[Tuple[Any, int], List[Dict[str, Any]]]:
    """Index prints by (ticker, second) so pairing is near-linear, not O(n^2).

    Pair hypotheses only ever look within ±_PAIR_WINDOW_S at the same ticker, so
    a full cross-scan is wasted work: at 2000 rows it cost ~4.5s, which is far
    too slow for a polled endpoint. Bucketing keeps the semantics identical.
    """
    idx: Dict[Tuple[Any, int], List[Dict[str, Any]]] = {}
    for row in batch:
        t = _secs(row.get("time_et"))
        if t is None:
            continue
        idx.setdefault((row.get("ticker"), t), []).append(row)
    return idx


def _pair_context(row: Dict[str, Any], batch: List[Dict[str, Any]], self_id: str,
                  index: Optional[Dict[Tuple[Any, int], List[Dict[str, Any]]]] = None
                  ) -> Dict[str, List[Dict[str, Any]]]:
    """Find same-batch prints that could pair with this one.

    Pairing is what makes roll / spread-leg hypotheses possible at all — a single
    print in isolation can never evidence either. Returns candidate partners only;
    it never asserts a relationship.
    """
    out: Dict[str, List[Dict[str, Any]]] = {"roll": [], "spread": [], "vol": []}
    t = _secs(row.get("time_et"))
    if t is None:
        return out
    tk = row.get("ticker")
    ct = (row.get("contract_type") or "").upper()
    exp = row.get("expiration")
    strike = row.get("strike")
    agg = _SIDE_CODE_AGGRESSION.get(str(row.get("trade_side_code") or "").upper())

    # Only prints inside the pair window at the same ticker can ever match.
    if index is not None:
        window: List[Dict[str, Any]] = []
        w = int(_PAIR_WINDOW_S)
        for dt_ in range(-w, w + 1):
            window.extend(index.get((tk, t + dt_), ()))
    else:  # pragma: no cover - fallback for single-event calls
        window = [o for o in batch if o.get("ticker") == tk]

    for other in window:
        oid = other.get("_event_id")
        if not oid or oid == self_id:
            continue
        ot = _secs(other.get("time_et"))
        if ot is None or abs(ot - t) > _PAIR_WINDOW_S:
            continue
        oct_ = (other.get("contract_type") or "").upper()
        oexp = other.get("expiration")
        ostrike = other.get("strike")
        oagg = _SIDE_CODE_AGGRESSION.get(str(other.get("trade_side_code") or "").upper())
        opposite = (agg in _BUY_SIDE and oagg in _SELL_SIDE) or \
                   (agg in _SELL_SIDE and oagg in _BUY_SIDE)

        # Roll candidate: same right, different expiration, opposing aggression.
        if oct_ == ct and oexp and exp and oexp != exp and opposite:
            out["roll"].append(other)
        # Spread-leg candidate: same right + same expiration, different strike.
        elif oct_ == ct and oexp == exp and ostrike is not None and strike is not None \
                and ostrike != strike:
            out["spread"].append(other)
        # Volatility-structure candidate: call+put, same expiration, same instant.
        elif oct_ and ct and oct_ != ct and oexp == exp:
            out["vol"].append(other)
    return out


def _intent_hypotheses(facts: Dict[str, Any], structure: str, aggression: str,
                       size_class: str, bias: str, pairs: Dict[str, List[Dict[str, Any]]],
                       spot: Optional[float]) -> Tuple[List[Dict[str, Any]],
                                                       List[Dict[str, Any]], List[str]]:
    """Layer 3 — hypotheses only. Each carries confidence + basis, never certainty."""
    possible: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    warnings: List[str] = []

    # Opening vs closing is NOT derivable without open interest. Never guessed.
    excluded.append({
        "intent": POSSIBLE_OPENING,
        "reason": "Open interest is not present in provider flow rows; a volume-to-open-"
                  "interest comparison is impossible, so opening cannot be distinguished "
                  "from closing.",
    })
    excluded.append({
        "intent": POSSIBLE_CLOSING,
        "reason": "Same as opening: no open interest on the print.",
    })
    warnings.append("Open interest unavailable — opening/closing intent excluded, not inferred.")

    if aggression == UNKNOWN_AGGRESSION:
        possible.append({
            "intent": DIRECTIONAL_UNCERTAIN, "confidence": 1.0,
            "basis": "Execution side is not observable, so no directional reading is supported.",
        })
        return possible, excluded, warnings

    # Roll — requires an opposing print in another expiration, same right.
    if pairs.get("roll"):
        partner = pairs["roll"][0]
        possible.append({
            "intent": LIKELY_ROLL,
            "confidence": 0.55,
            "basis": (f"Opposing {facts.get('contract_type')} print at expiration "
                      f"{partner.get('expiration')} within {int(_PAIR_WINDOW_S)}s "
                      f"(event {partner.get('_event_id')}). Consistent with a roll; "
                      f"the two prints cannot be proven to share an owner."),
            "related_event_ids": [p.get("_event_id") for p in pairs["roll"][:5]],
        })

    # Spread leg — same right + expiration, different strike, same instant.
    if pairs.get("spread"):
        partner = pairs["spread"][0]
        possible.append({
            "intent": SPREAD_LEG_CANDIDATE,
            "confidence": 0.50,
            "basis": (f"Concurrent {facts.get('contract_type')} print at strike "
                      f"{partner.get('strike')} in the same expiration "
                      f"(event {partner.get('_event_id')}). Consistent with a vertical "
                      f"leg; leg linkage is not provided by the feed."),
            "related_event_ids": [p.get("_event_id") for p in pairs["spread"][:5]],
        })
        possible.append({
            "intent": DIRECTIONAL_UNCERTAIN, "confidence": 0.50,
            "basis": "If this print is a spread leg, its standalone directional reading is misleading.",
        })

    # Volatility structure — call+put, same expiration, same instant.
    if pairs.get("vol"):
        partner = pairs["vol"][0]
        possible.append({
            "intent": POSSIBLE_VOLATILITY_TRADE,
            "confidence": 0.40,
            "basis": (f"Concurrent {partner.get('contract_type')} print in the same "
                      f"expiration (event {partner.get('_event_id')}). Consistent with a "
                      f"straddle/strangle leg rather than a directional bet."),
            "related_event_ids": [p.get("_event_id") for p in pairs["vol"][:5]],
        })

    # Hedge — deliberately weak. Protective puts and bearish puts look identical
    # on the tape; only the buyer's book distinguishes them, and we can't see it.
    ct = (facts.get("contract_type") or "").upper()
    strike = _safe_float(facts.get("strike"))
    if ct == "PUT" and aggression in _BUY_SIDE and size_class == INSTITUTIONAL_SIZE:
        if spot and strike and strike < spot * 0.98:
            possible.append({
                "intent": POSSIBLE_HEDGE,
                "confidence": 0.30,
                "basis": (f"Institutional-size OTM put purchase (strike {strike:g} vs spot "
                          f"{spot:g}). Consistent with portfolio protection, but identical on "
                          f"the tape to a directional bearish bet — the underlying position "
                          f"is not observable."),
            })
        else:
            possible.append({
                "intent": POSSIBLE_HEDGE, "confidence": 0.20,
                "basis": "Institutional-size put purchase; protection vs. directional intent "
                         "is not distinguishable from the print alone.",
            })

    # Directional position — the mechanical reading, explicitly a hypothesis.
    if bias in ("BULLISH", "BEARISH"):
        conf = 0.45 if structure in (SWEEP, BLOCK) else 0.35
        if pairs.get("spread") or pairs.get("vol"):
            conf = 0.20  # a leg of something larger is likelier
        possible.append({
            "intent": POSSIBLE_DIRECTIONAL,
            "confidence": round(conf, 2),
            "basis": (f"{aggression.replace('_', ' ').title()} in {ct}s leans {bias.lower()} "
                      f"as a transaction. Not evidence of the buyer's net exposure."),
        })

    if aggression == PASSIVE_MID:
        possible.append({
            "intent": DIRECTIONAL_UNCERTAIN, "confidence": 0.70,
            "basis": "Midpoint fill — the initiating side is not observable.",
        })

    return possible, excluded, warnings


def classify_flow_event(row: Dict[str, Any], *,
                        batch: Optional[List[Dict[str, Any]]] = None,
                        spot: Optional[float] = None,
                        as_of_secs: Optional[int] = None,
                        _pair_index: Optional[Dict[Tuple[Any, int], List[Dict[str, Any]]]] = None
                        ) -> Dict[str, Any]:
    """Classify a single normalized flow row. Never raises.

    Args:
        row:        a normalized row from `flow_tape.build_flow_tape`.
        batch:      sibling rows (each carrying `_event_id`) for pair context.
        spot:       underlying price from the bus, for moneyness only.
        as_of_secs: seconds-since-midnight ET "now", for delayed-print detection.
    """
    try:
        facts = _observable_facts(row)
        event_id = row.get("_event_id") or make_event_id(row)
        warnings: List[str] = []
        evidence: List[str] = []

        # ── malformed / unusable prints ────────────────────────────────────
        contracts = _safe_float(facts.get("contracts"), 0.0) or 0.0
        premium = _safe_float(facts.get("premium"), 0.0) or 0.0
        ct = (facts.get("contract_type") or "").upper()
        malformed = (not facts.get("ticker")) or ct not in ("CALL", "PUT") \
            or contracts <= 0 or premium <= 0
        if malformed:
            reasons = []
            if not facts.get("ticker"):
                reasons.append("missing ticker")
            if ct not in ("CALL", "PUT"):
                reasons.append(f"contract_type={facts.get('contract_type')!r}")
            if contracts <= 0:
                reasons.append("zero/absent contract volume")
            if premium <= 0:
                reasons.append("zero/absent premium")
            return {
                "event_id": event_id,
                "ticker": facts.get("ticker"),
                "timestamp": facts.get("time_et"),
                "classification": AMBIGUOUS,
                "classification_confidence": 0.0,
                "directional_bias": "UNCERTAIN",
                "directional_confidence": 0.0,
                "execution_aggression": UNKNOWN_AGGRESSION,
                "size_class": None,
                "possible_intents": [],
                "excluded_intents": [{"intent": "all",
                                      "reason": "Event is malformed; no interpretation attempted."}],
                "observable_facts": facts,
                "evidence": [],
                "warnings": [f"Malformed event: {', '.join(reasons)}."],
                "data_quality": DEGRADED,
                "classifier_version": CLASSIFIER_VERSION,
            }

        structure, struct_conf, struct_ev = _classify_structure(facts)
        aggression, agg_ev, agg_warn = _classify_aggression(facts)
        size_class, size_ev = _classify_size(facts)
        bias, bias_conf = _directional_lean(ct, aggression)
        evidence += struct_ev + agg_ev + size_ev
        warnings += agg_warn

        pairs = _pair_context(row, batch or [], event_id, _pair_index) if batch else \
            {"roll": [], "spread": [], "vol": []}
        possible, excluded, intent_warn = _intent_hypotheses(
            facts, structure, aggression, size_class, bias, pairs, spot)
        warnings += intent_warn

        # ── data quality ───────────────────────────────────────────────────
        quality = COMPLETE
        if aggression == UNKNOWN_AGGRESSION:
            quality = DEGRADED
        elif not facts.get("expiration") or facts.get("strike") is None:
            quality = PARTIAL
            warnings.append("Strike or expiration missing — contract identity incomplete.")

        # Delayed print (the provider gives no quote timestamps; print age is
        # the only freshness signal available).
        t = _secs(facts.get("time_et"))
        if as_of_secs is not None and t is not None:
            age = as_of_secs - t
            if age > _DELAYED_PRINT_S:
                warnings.append(f"Delayed print — {int(age)}s old at classification time.")
                if quality == COMPLETE:
                    quality = PARTIAL
        elif t is None:
            warnings.append("Unparseable timestamp — pairing and ordering unavailable.")
            if quality == COMPLETE:
                quality = PARTIAL

        # Spread legs make the standalone directional read unreliable.
        if pairs.get("spread") or pairs.get("vol"):
            bias_conf = round(bias_conf * 0.5, 2)

        return {
            "event_id": event_id,
            "ticker": facts.get("ticker"),
            "timestamp": facts.get("time_et"),
            "classification": structure,
            "classification_confidence": round(struct_conf, 2),
            "directional_bias": bias,
            "directional_confidence": round(bias_conf, 2),
            "execution_aggression": aggression,
            "size_class": size_class,
            "possible_intents": possible,
            "excluded_intents": excluded,
            "observable_facts": facts,
            "evidence": evidence,
            "warnings": warnings,
            "data_quality": quality,
            "classifier_version": CLASSIFIER_VERSION,
        }
    except Exception as e:  # pragma: no cover - defensive; classifier must never break the tape
        return {
            "event_id": row.get("_event_id") or "unknown",
            "ticker": row.get("ticker"),
            "timestamp": row.get("time_et"),
            "classification": AMBIGUOUS,
            "classification_confidence": 0.0,
            "directional_bias": "UNCERTAIN",
            "directional_confidence": 0.0,
            "execution_aggression": UNKNOWN_AGGRESSION,
            "size_class": None,
            "possible_intents": [],
            "excluded_intents": [],
            "observable_facts": {},
            "evidence": [],
            "warnings": [f"Classifier recovered from error: {e}"],
            "data_quality": DEGRADED,
            "classifier_version": CLASSIFIER_VERSION,
        }


def classify_flow_events(rows: List[Dict[str, Any]], *,
                         spot: Optional[float] = None,
                         as_of_secs: Optional[int] = None) -> Dict[str, Any]:
    """Classify a batch of normalized flow rows. Read-only; never mutates inputs.

    Batch context is what makes roll / spread-leg / volatility hypotheses
    possible — they cannot be evidenced by a single print.
    """
    if not rows:
        return {
            "available": True, "count": 0, "events": [],
            "summary": _summarize([]),
            "classifier_version": CLASSIFIER_VERSION,
        }
    # Work on shallow copies so the caller's rows are never mutated.
    batch: List[Dict[str, Any]] = []
    for r in rows:
        c = dict(r)
        c["_event_id"] = make_event_id(r)
        batch.append(c)

    index = _build_pair_index(batch)
    events = [classify_flow_event(r, batch=batch, spot=spot, as_of_secs=as_of_secs,
                                  _pair_index=index)
              for r in batch]
    return {
        "available": True,
        "count": len(events),
        "events": events,
        "summary": _summarize(events),
        "classifier_version": CLASSIFIER_VERSION,
    }


def _summarize(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate counts. Deliberately reports uncertainty alongside the totals."""
    by_class: Dict[str, int] = {}
    by_size: Dict[str, int] = {}
    by_quality: Dict[str, int] = {}
    bullish = bearish = uncertain = 0
    for e in events:
        by_class[e.get("classification")] = by_class.get(e.get("classification"), 0) + 1
        if e.get("size_class"):
            by_size[e["size_class"]] = by_size.get(e["size_class"], 0) + 1
        by_quality[e.get("data_quality")] = by_quality.get(e.get("data_quality"), 0) + 1
        b = e.get("directional_bias")
        if b == "BULLISH":
            bullish += 1
        elif b == "BEARISH":
            bearish += 1
        else:
            uncertain += 1
    return {
        "by_classification": by_class,
        "by_size_class": by_size,
        "by_data_quality": by_quality,
        "directional_lean": {"bullish": bullish, "bearish": bearish, "uncertain": uncertain},
        "note": ("Counts describe observed prints and their mechanical lean. They are not "
                 "evidence of institutional positioning or intent."),
    }


def health() -> Dict[str, Any]:
    """Diagnostics + freshness surface for the classifier itself."""
    return {
        "enabled": FLOW_CLASSIFIER_ENABLED,
        "classifier_version": CLASSIFIER_VERSION,
        "thresholds": {
            "institutional_premium": _INSTITUTIONAL_PREMIUM,
            "retail_premium": _RETAIL_PREMIUM,
            "pair_window_s": _PAIR_WINDOW_S,
            "delayed_print_s": _DELAYED_PRINT_S,
        },
        "unavailable_fields": [
            "open_interest (opening/closing intent excluded)",
            "exchange_sequence (sweep taken as provider-reported)",
            "quote_at_trade (no spread-quality claims)",
            "implied_volatility / greeks (no IV-contribution claims)",
        ],
        "supported_classifications": [SWEEP, BLOCK, SPLIT, SINGLE_LEG, AMBIGUOUS],
        "supported_size_classes": [INSTITUTIONAL_SIZE, MID_SIZE, RETAIL_SIZE_NOISE],
        "supported_intents": [
            SPREAD_LEG_CANDIDATE, LIKELY_ROLL, POSSIBLE_HEDGE,
            POSSIBLE_DIRECTIONAL, POSSIBLE_VOLATILITY_TRADE, DIRECTIONAL_UNCERTAIN,
        ],
        "excluded_intents_always": [POSSIBLE_OPENING, POSSIBLE_CLOSING],
    }

"""
APEX — Institutional Daily Key Levels & Trade Map Engine.

Location: engine/key_levels/daily_key_levels.py

Scope of THIS file (the buildable spine):
  * typed level model + a hard no-fabrication sentinel (FEED_REQUIRED)
  * deterministic calculators that need only OHLC / overnight / opening bars:
    previous session, overnight, opening range, initial balance + extensions,
    expected move (straddle- and IV-implied)
  * provider Protocols for everything that must come from an existing APEX
    source of truth (market data, gamma, volume profile, liquidity) — so this
    engine DEPENDS ON those engines and never re-derives their data
  * Trade Map (dynamic), level ranking (dynamic), risk gate, and the
    Morning-Brief section renderer (15/16/17)

Deliberately NOT in this file:
  * real provider adapters — they bind to Polygon / QuantData / the gamma
    provider / the Volume Profile Engine, whose client signatures live in your
    repo, not here. Implement them against the Protocols below.
  * the dashboard panel (Module 9) — it binds to the JSON from `.to_dict()`;
    build it once this contract is stable.
  * the Institutional Bias number (Module 6) — see `bias.py` note: it must
    REUSE the APEX 46 Consensus/Conviction layer, not re-weight from scratch.

Rule enforced structurally: a value is either real or FEED_REQUIRED. There is
no third "estimated" state, so nothing downstream can fabricate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol, Sequence, Union, runtime_checkable


# --------------------------------------------------------------------------- #
# No-fabrication sentinel
# --------------------------------------------------------------------------- #

class _FeedRequired:
    """Singleton marking a value that MUST come from a feed and isn't here yet.
    Falsy, and prints as [FEED REQUIRED] so it renders correctly everywhere."""
    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self) -> str:
        return "[FEED REQUIRED]"

    def __bool__(self) -> bool:
        return False


FEED_REQUIRED = _FeedRequired()
Maybe = Union[float, _FeedRequired]   # a number, or explicitly absent


def present(x: Maybe) -> bool:
    """True only for an actually available value.

    ``None`` can enter at provider/session boundaries when a feed is legitimately
    unavailable (for example a closed-market morning brief). Treat it exactly
    like ``FEED_REQUIRED`` so downstream arithmetic never sees a null as data.
    """
    return x is not None and not isinstance(x, _FeedRequired)


def _api_number(value):
    """Return a finite JSON numeric value or None.

    Structured analytics must never contain presentation sentinels such as
    ``[FEED REQUIRED]``. Those labels belong only in the Markdown renderer.
    """
    if isinstance(value, bool) or isinstance(value, _FeedRequired) or value is None:
        return None
    try:
        from math import isfinite
        number = float(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _sub(a: Maybe, b: Maybe) -> Maybe:
    return (a - b) if present(a) and present(b) else FEED_REQUIRED


def _mid(a: Maybe, b: Maybe) -> Maybe:
    return ((a + b) / 2.0) if present(a) and present(b) else FEED_REQUIRED


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #

class LevelKind(Enum):
    PDH = "prev_day_high"; PDL = "prev_day_low"
    PREV_CLOSE = "prev_close"; PREV_OPEN = "prev_open"; PREV_SETTLE = "prev_settlement"
    ON_HIGH = "overnight_high"; ON_LOW = "overnight_low"; ON_MID = "overnight_mid"
    ON_VWAP = "overnight_vwap"
    OR5_H = "or5_high"; OR5_L = "or5_low"; OR15_H = "or15_high"; OR15_L = "or15_low"
    IB_H = "ib_high"; IB_L = "ib_low"; IB_EXT = "ib_extension"
    DEV_POC = "developing_poc"; PREV_POC = "prev_poc"; COMP_POC = "composite_poc"
    VAH = "vah"; VAL = "val"; COMP_VAH = "composite_vah"; COMP_VAL = "composite_val"
    HVN = "high_volume_node"; LVN = "low_volume_node"
    NAKED_POC = "naked_poc"; VIRGIN_POC = "virgin_poc"
    GAMMA_FLIP = "gamma_flip"; ZERO_GAMMA = "zero_gamma"
    CALL_WALL = "call_wall"; PUT_WALL = "put_wall"
    HI_GAMMA = "high_gamma_strike"; LO_GAMMA = "low_gamma_strike"
    VOL_TRIGGER = "volatility_trigger"
    EM_UPPER = "em_upper"; EM_LOWER = "em_lower"
    BSL = "buyside_liquidity"; SSL = "sellside_liquidity"
    EQ_HIGH = "equal_highs"; EQ_LOW = "equal_lows"
    FVG = "fair_value_gap"; LIQ_POOL = "liquidity_pool"; UNFILLED_GAP = "unfilled_gap"
    SWING_HIGH = "swing_high"; SWING_LOW = "swing_low"
    OPT_STRIKE = "large_option_strike"; HEDGE_ZONE = "dealer_hedge_zone"


class LevelSource(Enum):
    COMPUTED = "computed"           # derived here from raw bars
    POLYGON = "polygon"
    QUANTDATA = "quantdata"
    GAMMA_PROVIDER = "gamma_provider"
    VOLUME_PROFILE = "volume_profile_engine"
    LIQUIDITY = "liquidity_engine"


class GammaRegime(Enum):
    LONG_GAMMA = "long_gamma"       # dealers dampen -> mean reversion
    SHORT_GAMMA = "short_gamma"     # dealers amplify -> momentum
    NEUTRAL_GAMMA = "neutral_gamma"
    UNKNOWN = "unknown"


# --------------------------------------------------------------------------- #
# Core level model
# --------------------------------------------------------------------------- #

@dataclass
class KeyLevel:
    kind: LevelKind
    price: Maybe
    source: LevelSource
    strength_score: Maybe = FEED_REQUIRED       # 0..1, from prior-reaction history
    prior_reactions: Maybe = FEED_REQUIRED      # count
    # probabilities are CALIBRATED-or-absent, never guessed (see class docstring)
    reaction_prob: Maybe = FEED_REQUIRED
    break_prob: Maybe = FEED_REQUIRED
    reversal_prob: Maybe = FEED_REQUIRED
    magnet_score: Maybe = FEED_REQUIRED
    label: str = ""
    instrument: str = "SPX"          # instrument the level was computed on (SPX/ES/SPY)
    normalized: bool = False         # True once translated into SPX points via basis

    def distance(self, spot: Maybe) -> Maybe:
        return _sub(self.price, spot)

    def to_dict(self, spot: Maybe = FEED_REQUIRED) -> dict:
        d = self.distance(spot)
        return {
            "kind": self.kind.value,
            "price": self.price if present(self.price) else str(FEED_REQUIRED),
            "source": self.source.value,
            "strength": _api_number(self.strength_score),
            "prior_reactions": _api_number(self.prior_reactions),
            "distance": round(float(d), 2) if _api_number(d) is not None else None,
            "reaction_prob": _api_number(self.reaction_prob),
            "break_prob": _api_number(self.break_prob),
            "reversal_prob": _api_number(self.reversal_prob),
            "magnet": _api_number(self.magnet_score),
            "label": self.label,
            "instrument": self.instrument,
            "normalized": self.normalized,
        }


# --------------------------------------------------------------------------- #
# Provider Protocols — the seams to your existing single-source-of-truth engines
# --------------------------------------------------------------------------- #

@dataclass
class Bar:
    o: float; h: float; l: float; c: float
    v: Maybe = FEED_REQUIRED
    delta: Maybe = FEED_REQUIRED     # signed volume, if available


@runtime_checkable
class MarketDataProvider(Protocol):
    """Polygon / QuantData adapter. Any method may return FEED_REQUIRED-bearing
    data; it must NEVER invent values."""
    def previous_session(self) -> dict: ...          # {open, high, low, close, settlement}
    def overnight_bars(self) -> Sequence[Bar]: ...   # globex session bars
    def opening_bars(self) -> Sequence[Bar]: ...     # RTH 1-min bars from the open
    def spot(self) -> Maybe: ...
    def atm_straddle(self) -> Maybe: ...             # price of ATM straddle
    def atm_iv(self) -> Maybe: ...                   # annualized
    def time_to_close_frac(self) -> Maybe: ...       # fraction of trading year remaining today
    def atr(self, n: int = 14) -> Maybe: ...
    def avg_daily_range(self, n: int = 20) -> Maybe: ...


@runtime_checkable
class GammaProvider(Protocol):
    def levels(self) -> dict: ...    # {gamma_flip, zero_gamma, call_wall, put_wall,
                                     #  hi_gamma, lo_gamma, vol_trigger}
    def dealer_position(self) -> GammaRegime: ...
    def dealer_delta(self) -> Maybe: ...


@runtime_checkable
class VolumeProfileProvider(Protocol):
    def levels(self) -> dict: ...    # {dev_poc, prev_poc, comp_poc, vah, val,
                                     #  comp_vah, comp_val, hvns[], lvns[],
                                     #  naked_pocs[], virgin_pocs[]}


@runtime_checkable
class LiquidityProvider(Protocol):
    def levels(self) -> Sequence[KeyLevel]: ...   # already-typed liquidity levels


# --------------------------------------------------------------------------- #
# Deterministic calculators (need only raw bars — safe to compute here)
# --------------------------------------------------------------------------- #

def previous_session_levels(md: MarketDataProvider) -> list[KeyLevel]:
    s = md.previous_session() or {}
    g = lambda k: s.get(k, FEED_REQUIRED)
    return [
        KeyLevel(LevelKind.PDH, g("high"), LevelSource.POLYGON, label="Prev Day High"),
        KeyLevel(LevelKind.PDL, g("low"), LevelSource.POLYGON, label="Prev Day Low"),
        KeyLevel(LevelKind.PREV_CLOSE, g("close"), LevelSource.POLYGON, label="Prev Close"),
        KeyLevel(LevelKind.PREV_OPEN, g("open"), LevelSource.POLYGON, label="Prev Open"),
        KeyLevel(LevelKind.PREV_SETTLE, g("settlement"), LevelSource.POLYGON, label="Prev Settlement"),
    ]


def overnight_levels(md: MarketDataProvider) -> tuple[list[KeyLevel], dict]:
    bars = list(md.overnight_bars() or [])
    if not bars:
        empty = FEED_REQUIRED
        levels = [
            KeyLevel(LevelKind.ON_HIGH, empty, LevelSource.POLYGON, label="Overnight High"),
            KeyLevel(LevelKind.ON_LOW, empty, LevelSource.POLYGON, label="Overnight Low"),
            KeyLevel(LevelKind.ON_MID, empty, LevelSource.COMPUTED, label="Overnight Mid"),
        ]
        return levels, {"range": empty, "vwap": empty, "delta": empty}

    hi = max(b.h for b in bars)
    lo = min(b.l for b in bars)
    mid = _mid(hi, lo)
    rng = _sub(hi, lo)

    # VWAP / delta only if volume/delta present on the bars, else FEED_REQUIRED
    if all(present(b.v) for b in bars):
        num = sum(((b.h + b.l + b.c) / 3.0) * b.v for b in bars)
        den = sum(b.v for b in bars)
        vwap: Maybe = (num / den) if den else FEED_REQUIRED
    else:
        vwap = FEED_REQUIRED
    delta: Maybe = sum(b.delta for b in bars) if all(present(b.delta) for b in bars) else FEED_REQUIRED

    levels = [
        KeyLevel(LevelKind.ON_HIGH, hi, LevelSource.POLYGON, label="Overnight High"),
        KeyLevel(LevelKind.ON_LOW, lo, LevelSource.POLYGON, label="Overnight Low"),
        KeyLevel(LevelKind.ON_MID, mid, LevelSource.COMPUTED, label="Overnight Mid"),
        KeyLevel(LevelKind.ON_VWAP, vwap, LevelSource.COMPUTED, label="Overnight VWAP"),
    ]
    return levels, {"range": rng, "vwap": vwap, "delta": delta}


def opening_and_ib_levels(md: MarketDataProvider) -> list[KeyLevel]:
    bars = list(md.opening_bars() or [])
    out: list[KeyLevel] = []

    def rng_levels(mins: int, kh: LevelKind, kl: LevelKind, tag: str):
        window = bars[:mins]
        if len(window) < mins:
            out.append(KeyLevel(kh, FEED_REQUIRED, LevelSource.POLYGON, label=f"{tag} High"))
            out.append(KeyLevel(kl, FEED_REQUIRED, LevelSource.POLYGON, label=f"{tag} Low"))
            return
        out.append(KeyLevel(kh, max(b.h for b in window), LevelSource.COMPUTED, label=f"{tag} High"))
        out.append(KeyLevel(kl, min(b.l for b in window), LevelSource.COMPUTED, label=f"{tag} Low"))

    rng_levels(5, LevelKind.OR5_H, LevelKind.OR5_L, "OR 5m")
    rng_levels(15, LevelKind.OR15_H, LevelKind.OR15_L, "OR 15m")

    # Initial balance = first 60 minutes
    ib = bars[:60]
    if len(ib) >= 60:
        ibh, ibl = max(b.h for b in ib), min(b.l for b in ib)
        ibr = ibh - ibl
        out.append(KeyLevel(LevelKind.IB_H, ibh, LevelSource.COMPUTED, label="IB High"))
        out.append(KeyLevel(LevelKind.IB_L, ibl, LevelSource.COMPUTED, label="IB Low"))
        for n in (1, 2):
            out.append(KeyLevel(LevelKind.IB_EXT, ibh + n * ibr, LevelSource.COMPUTED,
                                label=f"IB +{n}x Extension"))
            out.append(KeyLevel(LevelKind.IB_EXT, ibl - n * ibr, LevelSource.COMPUTED,
                                label=f"IB -{n}x Extension"))
    else:
        out.append(KeyLevel(LevelKind.IB_H, FEED_REQUIRED, LevelSource.POLYGON, label="IB High"))
        out.append(KeyLevel(LevelKind.IB_L, FEED_REQUIRED, LevelSource.POLYGON, label="IB Low"))
    return out


@dataclass
class ExpectedMove:
    spot: Maybe
    em_1sigma: Maybe
    upper: Maybe
    lower: Maybe
    em_2sigma: Maybe
    expected_daily_range: Maybe
    straddle_implied: Maybe
    iv_implied: Maybe
    atr: Maybe
    avg_daily_range: Maybe
    confidence: Maybe           # heuristic agreement of straddle vs IV; flagged below
    confidence_basis: str = "straddle/IV agreement (heuristic, not calibrated)"

    def levels(self) -> list[KeyLevel]:
        return [
            KeyLevel(LevelKind.EM_UPPER, self.upper, LevelSource.COMPUTED, label="Expected Move Upper"),
            KeyLevel(LevelKind.EM_LOWER, self.lower, LevelSource.COMPUTED, label="Expected Move Lower"),
        ]


def expected_move(md: MarketDataProvider) -> ExpectedMove:
    spot = md.spot()
    straddle = md.atm_straddle()
    iv = md.atm_iv()
    T = md.time_to_close_frac()

    # straddle-implied 1σ ≈ 0.85 * ATM straddle (standard desk approximation)
    em_straddle: Maybe = (0.85 * straddle) if present(straddle) else FEED_REQUIRED
    # IV-implied 1σ = spot * IV * sqrt(T)
    if present(spot) and present(iv) and present(T) and T >= 0:
        em_iv: Maybe = spot * iv * (T ** 0.5)
    else:
        em_iv = FEED_REQUIRED

    # prefer straddle; fall back to IV
    em1 = em_straddle if present(em_straddle) else em_iv
    upper = (spot + em1) if present(spot) and present(em1) else FEED_REQUIRED
    lower = (spot - em1) if present(spot) and present(em1) else FEED_REQUIRED
    em2 = (2 * em1) if present(em1) else FEED_REQUIRED
    edr = (2 * em1) if present(em1) else FEED_REQUIRED

    # heuristic confidence: how closely straddle- and IV-implied agree (0..1)
    if present(em_straddle) and present(em_iv) and em_straddle > 0:
        div = abs(em_straddle - em_iv) / em_straddle
        conf: Maybe = max(0.0, 1.0 - min(1.0, div))
    else:
        conf = FEED_REQUIRED

    return ExpectedMove(spot, em1, upper, lower, em2, edr,
                        em_straddle, em_iv, md.atr(), md.avg_daily_range(), conf)


# --------------------------------------------------------------------------- #
# Gamma / Volume Profile assembly (provider-sourced, FEED_REQUIRED-safe)
# --------------------------------------------------------------------------- #

@dataclass
class GammaStructure:
    flip: Maybe; zero_gamma: Maybe; call_wall: Maybe; put_wall: Maybe
    hi_gamma: Maybe; lo_gamma: Maybe; vol_trigger: Maybe
    regime: GammaRegime; dealer_delta: Maybe

    def levels(self) -> list[KeyLevel]:
        m = [
            (LevelKind.GAMMA_FLIP, self.flip, "Gamma Flip"),
            (LevelKind.ZERO_GAMMA, self.zero_gamma, "Zero Gamma"),
            (LevelKind.CALL_WALL, self.call_wall, "Call Wall"),
            (LevelKind.PUT_WALL, self.put_wall, "Put Wall"),
            (LevelKind.HI_GAMMA, self.hi_gamma, "High Gamma Strike"),
            (LevelKind.LO_GAMMA, self.lo_gamma, "Low Gamma Strike"),
            (LevelKind.VOL_TRIGGER, self.vol_trigger, "Volatility Trigger"),
        ]
        return [KeyLevel(k, p, LevelSource.GAMMA_PROVIDER, label=lbl) for k, p, lbl in m]


def gamma_structure(gp: GammaProvider) -> GammaStructure:
    lv = gp.levels() or {}
    g = lambda k: lv.get(k, FEED_REQUIRED)
    regime = gp.dealer_position() if hasattr(gp, "dealer_position") else GammaRegime.UNKNOWN
    return GammaStructure(
        g("gamma_flip"), g("zero_gamma"), g("call_wall"), g("put_wall"),
        g("hi_gamma"), g("lo_gamma"), g("vol_trigger"),
        regime or GammaRegime.UNKNOWN, gp.dealer_delta(),
    )


def volume_profile_levels(vp: VolumeProfileProvider) -> list[KeyLevel]:
    lv = vp.levels() or {}
    out: list[KeyLevel] = []
    single = [
        (LevelKind.DEV_POC, "dev_poc", "Developing POC"),
        (LevelKind.PREV_POC, "prev_poc", "Previous POC"),
        (LevelKind.COMP_POC, "comp_poc", "Composite POC"),
        (LevelKind.VAH, "vah", "VAH"), (LevelKind.VAL, "val", "VAL"),
        (LevelKind.COMP_VAH, "comp_vah", "Composite VAH"),
        (LevelKind.COMP_VAL, "comp_val", "Composite VAL"),
    ]
    for kind, key, lbl in single:
        out.append(KeyLevel(kind, lv.get(key, FEED_REQUIRED), LevelSource.VOLUME_PROFILE, label=lbl))
    multi = [(LevelKind.HVN, "hvns", "HVN"), (LevelKind.LVN, "lvns", "LVN"),
             (LevelKind.NAKED_POC, "naked_pocs", "Naked POC"),
             (LevelKind.VIRGIN_POC, "virgin_pocs", "Virgin POC")]
    for kind, key, lbl in multi:
        for price in (lv.get(key) or []):
            out.append(KeyLevel(kind, price, LevelSource.VOLUME_PROFILE, label=lbl))
    return out


# --------------------------------------------------------------------------- #
# Value-area / position helpers
# --------------------------------------------------------------------------- #

def _first(levels: list[KeyLevel], kind: LevelKind) -> Optional[KeyLevel]:
    return next((l for l in levels if l.kind is kind and present(l.price)), None)


# --------------------------------------------------------------------------- #
# MODULE 7 — Trade Map (dynamic, only emits lines whose levels are present)
# --------------------------------------------------------------------------- #

@dataclass
class TradeMapLine:
    condition: str
    implication: str
    regime_hint: str


def trade_map(spot: Maybe, levels: list[KeyLevel], gamma: GammaStructure,
              em: ExpectedMove) -> list[TradeMapLine]:
    lines: list[TradeMapLine] = []
    if not present(spot):
        return [TradeMapLine("spot unavailable", str(FEED_REQUIRED), "n/a")]

    pdh, pdl = _first(levels, LevelKind.PDH), _first(levels, LevelKind.PDL)
    vah, val = _first(levels, LevelKind.VAH), _first(levels, LevelKind.VAL)

    if pdh:
        lines.append(TradeMapLine(f"Above PDH ({pdh.price})", "Bullish continuation possible.", "trend")
                     if spot > pdh.price else
                     TradeMapLine(f"Below PDH ({pdh.price})", "Supply overhead until reclaimed.", "balance"))
    if pdl:
        lines.append(TradeMapLine(f"Below PDL ({pdl.price})", "Bearish continuation possible.", "trend")
                     if spot < pdl.price else
                     TradeMapLine(f"Above PDL ({pdl.price})", "Demand beneath until lost.", "balance"))
    if vah and val:
        inside = val.price <= spot <= vah.price
        lines.append(TradeMapLine("Inside value", "Responsive auction expected.", "mean_reversion")
                     if inside else
                     TradeMapLine("Outside value", "Initiative auction expected.", "expansion"))
    # Dealer regime is the authoritative directional signal. Spot-vs-flip is
    # supplemental context only when a genuine local zero crossing is available.
    if gamma.regime == GammaRegime.SHORT_GAMMA:
        lines.append(TradeMapLine("Dealer gamma regime: SHORT",
                                  "Momentum/expansion risk; dealer hedging may amplify moves.", "momentum"))
    elif gamma.regime == GammaRegime.LONG_GAMMA:
        lines.append(TradeMapLine("Dealer gamma regime: LONG",
                                  "Mean-reversion/pinning risk; dealer hedging may dampen moves.", "mean_reversion"))
    elif gamma.regime == GammaRegime.NEUTRAL_GAMMA:
        lines.append(TradeMapLine("Dealer gamma regime: MIXED",
                                  "Gamma is not providing a strong directional volatility bias.", "balance"))

    if isinstance(gamma.flip, (int, float)):
        relation = "Above" if spot >= gamma.flip else "Below"
        lines.append(TradeMapLine(f"{relation} reported zero-gamma reference ({gamma.flip})",
                                  "Contextual zero-crossing reference; validate provider provenance before local use.",
                                  "context"))
    if present(gamma.call_wall) and spot > gamma.call_wall:
        lines.append(TradeMapLine(f"Above Call Wall ({gamma.call_wall})",
                                  "Dealer unwind / pin risk possible.", "expansion"))
    if present(gamma.put_wall) and spot < gamma.put_wall:
        lines.append(TradeMapLine(f"Below Put Wall ({gamma.put_wall})",
                                  "Hedging acceleration risk increases.", "expansion"))
    if present(em.upper) and present(em.lower):
        inside_em = em.lower <= spot <= em.upper
        lines.append(TradeMapLine("Inside expected move", "Normal auction.", "balance")
                     if inside_em else
                     TradeMapLine("Outside expected move", "Expansion likely; EM breached.", "expansion"))
    return lines


# --------------------------------------------------------------------------- #
# MODULE 8 — Highest-probability level ranking (dynamic, not a fixed list)
# --------------------------------------------------------------------------- #

# base institutional weight by kind (magnet propensity), before proximity/strength
_BASE_WEIGHT = {
    LevelKind.GAMMA_FLIP: 1.00, LevelKind.DEV_POC: 0.95, LevelKind.COMP_POC: 0.90,
    LevelKind.CALL_WALL: 0.85, LevelKind.PUT_WALL: 0.85, LevelKind.VAH: 0.70,
    LevelKind.VAL: 0.70, LevelKind.PDH: 0.75, LevelKind.PDL: 0.75,
    LevelKind.ON_HIGH: 0.60, LevelKind.ON_LOW: 0.60, LevelKind.LVN: 0.65,
    LevelKind.NAKED_POC: 0.80, LevelKind.PREV_POC: 0.70,
    # liquidity structure
    LevelKind.LIQ_POOL: 0.78, LevelKind.BSL: 0.72, LevelKind.SSL: 0.72,
    LevelKind.EQ_HIGH: 0.66, LevelKind.EQ_LOW: 0.66, LevelKind.FVG: 0.60,
    LevelKind.SWING_HIGH: 0.58, LevelKind.SWING_LOW: 0.58, LevelKind.OPT_STRIKE: 0.64,
}


@dataclass
class RankedLevel:
    level: KeyLevel
    importance: float
    proximity: Maybe


def rank_levels(spot: Maybe, levels: list[KeyLevel], top_n: int = 10) -> list[RankedLevel]:
    """Importance = base_weight * proximity_factor * (0.5 + 0.5*strength).
    Proximity favors nearer levels. Probabilities are NOT synthesized here —
    if you want reaction/break/reversal %, inject a calibrated model (see note)."""
    ranked: list[RankedLevel] = []
    # scale for proximity: use median abs distance so it's unit-agnostic
    dists = [abs(l.distance(spot)) for l in levels if present(l.distance(spot))]
    scale = (sorted(dists)[len(dists) // 2] if dists else 1.0) or 1.0
    for l in levels:
        if not present(l.price):
            continue
        base = _BASE_WEIGHT.get(l.kind, 0.5)
        d = l.distance(spot)
        if present(d):
            prox = 1.0 / (1.0 + abs(d) / scale)     # 1 at spot -> decays
        else:
            prox = 0.5
        strength_value = _api_number(l.strength_score)
        strength = strength_value if strength_value is not None else 0.5
        importance = base * prox * (0.5 + 0.5 * strength)
        ranked.append(RankedLevel(l, round(importance, 4), d if present(d) else FEED_REQUIRED))
    ranked.sort(key=lambda r: r.importance, reverse=True)
    return ranked[:top_n]


# --------------------------------------------------------------------------- #
# MODULE 11 — Risk gate: every recommendation must reference the map
# --------------------------------------------------------------------------- #

@dataclass
class RiskContext:
    nearest_gamma: Optional[KeyLevel]
    nearest_liquidity: Optional[KeyLevel]
    nearest_vp: Optional[KeyLevel]
    em_position: str                 # "inside" | "outside" | FEED_REQUIRED
    bias: str
    regime: str
    missing: list[str] = field(default_factory=list)
    confidence_cap: float = 1.0      # multiplier applied to any downstream confidence
    block_high_conviction: bool = False


_GAMMA_KINDS = {LevelKind.GAMMA_FLIP, LevelKind.ZERO_GAMMA, LevelKind.CALL_WALL,
                LevelKind.PUT_WALL, LevelKind.HI_GAMMA, LevelKind.LO_GAMMA, LevelKind.VOL_TRIGGER}
_LIQ_KINDS = {LevelKind.BSL, LevelKind.SSL, LevelKind.EQ_HIGH, LevelKind.EQ_LOW,
              LevelKind.FVG, LevelKind.LIQ_POOL, LevelKind.UNFILLED_GAP,
              LevelKind.SWING_HIGH, LevelKind.SWING_LOW, LevelKind.OPT_STRIKE, LevelKind.HEDGE_ZONE}
_VP_KINDS = {LevelKind.DEV_POC, LevelKind.PREV_POC, LevelKind.COMP_POC, LevelKind.VAH,
             LevelKind.VAL, LevelKind.HVN, LevelKind.LVN, LevelKind.NAKED_POC}


def _nearest(spot: Maybe, levels: list[KeyLevel], kinds: set) -> Optional[KeyLevel]:
    cands = [l for l in levels if l.kind in kinds and present(l.distance(spot))]
    return min(cands, key=lambda l: abs(l.distance(spot))) if cands else None


def build_risk_context(spot: Maybe, levels: list[KeyLevel], em: ExpectedMove,
                       bias: str, regime: str) -> RiskContext:
    ng = _nearest(spot, levels, _GAMMA_KINDS)
    nl = _nearest(spot, levels, _LIQ_KINDS)
    nvp = _nearest(spot, levels, _VP_KINDS)
    if present(em.upper) and present(em.lower) and present(spot):
        em_pos = "inside" if em.lower <= spot <= em.upper else "outside"
    else:
        em_pos = str(FEED_REQUIRED)

    missing = []
    if ng is None: missing.append("nearest_gamma_level")
    if nvp is None: missing.append("nearest_volume_profile_level")
    if em_pos == str(FEED_REQUIRED): missing.append("expected_move_position")
    if bias == str(FEED_REQUIRED): missing.append("institutional_bias")
    if regime == str(FEED_REQUIRED): missing.append("regime")

    cap = 1.0
    block = False
    if missing:
        cap = max(0.4, 1.0 - 0.15 * len(missing))
        block = True   # any required component missing -> no high-conviction alerts
    return RiskContext(ng, nl, nvp, em_pos, bias, regime, missing, round(cap, 2), block)


# --------------------------------------------------------------------------- #
# MODULE 10 — Morning-Brief sections 15/16/17
# --------------------------------------------------------------------------- #

def _is_number(value) -> bool:
    """True only for finite numeric values safe for report formatting."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        from math import isfinite
        return isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _fmt(v: Maybe, *, decimals: int = 2, thousands: bool = True) -> str:
    """Format numeric values while preserving categorical strings safely."""
    if not present(v) or v is None:
        return str(FEED_REQUIRED)
    if _is_number(v):
        spec = f",.{decimals}f" if thousands else f".{decimals}f"
        return format(float(v), spec)
    return str(v)


def render_brief_sections(spot: Maybe, levels: list[KeyLevel], gamma: GammaStructure,
                          em: ExpectedMove, tmap: list[TradeMapLine],
                          ranked: list[RankedLevel]) -> str:
    out = ["SECTION 15 — DAILY INSTITUTIONAL KEY LEVELS", ""]
    out.append(f"Spot: {_fmt(spot)}   Gamma regime: {gamma.regime.value}")
    for l in levels:
        if present(l.price):
            d = l.distance(spot)
            out.append(f"  {l.label:<24} {_fmt(l.price):>12}"
                       + (f"   ({d:+.2f})" if present(d) else ""))
        else:
            out.append(f"  {l.label:<24} {str(FEED_REQUIRED):>12}")
    out += ["",
            f"Expected Move  ±{_fmt(em.em_1sigma)}   "
            f"[{_fmt(em.lower)} .. {_fmt(em.upper)}]   "
            f"conf={_fmt(em.confidence)} ({em.confidence_basis})", ""]

    out += ["SECTION 16 — DAILY TRADE MAP", ""]
    for ln in tmap:
        out.append(f"  {ln.condition}  ->  {ln.implication}  [{ln.regime_hint}]")

    out += ["", "SECTION 17 — HIGHEST PROBABILITY LEVELS", ""]
    for i, r in enumerate(ranked, 1):
        out.append(f"  {i:>2}. {r.level.label:<22} {_fmt(r.level.price):>12}"
                   f"   importance={r.importance:.3f}")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #

@dataclass
class DailyKeyLevels:
    spot: Maybe
    levels: list[KeyLevel]
    gamma: GammaStructure
    expected_move: ExpectedMove
    trade_map: list[TradeMapLine]
    ranked: list[RankedLevel]

    @classmethod
    def build(cls, md: MarketDataProvider, gp: GammaProvider,
              vp: VolumeProfileProvider, lp: Optional[LiquidityProvider] = None,
              *, level_postprocess=None) -> "DailyKeyLevels":
        spot = md.spot()
        levels: list[KeyLevel] = []
        levels += previous_session_levels(md)
        on_levels, _ = overnight_levels(md)
        levels += on_levels
        levels += opening_and_ib_levels(md)
        em = expected_move(md)
        levels += em.levels()
        g = gamma_structure(gp)
        levels += g.levels()
        levels += volume_profile_levels(vp)
        if lp is not None:
            levels += list(lp.levels() or [])
        # Proxy levels (e.g. ES overnight) must be translated into SPX points
        # BEFORE the trade map / ranking compare them against SPX spot & gamma.
        if level_postprocess is not None:
            levels = level_postprocess(levels)
        # APEX 50.4.2.3: restore deterministic level analytics removed by the
        # formatting hotfix. Keep numeric values in the model; presentation
        # sentinels are applied only by render_brief_sections().
        try:
            from .level_analytics import enrich_level_analytics
        except ImportError:
            from level_analytics import enrich_level_analytics
        levels = enrich_level_analytics(spot, levels)
        # APEX 50.5.0: overlay evidence-based (calibrated) probabilities where
        # enough historical samples exist. Falls back to the heuristic values
        # above automatically (blend returns heuristic at n=0). Non-fatal.
        try:
            from .historical_level_calibration import enrich_levels_with_calibration
            symbol = getattr(levels[0], "instrument", "SPX") if levels else "SPX"
            ctx = {"gamma_regime": g.regime.value.upper() if getattr(g, "regime", None) else None}
            levels = enrich_levels_with_calibration(levels, ctx, symbol=str(symbol).upper())
        except Exception:
            pass
        tmap = trade_map(spot, levels, g, em)
        ranked = rank_levels(spot, levels)
        return cls(spot, levels, g, em, tmap, ranked)

    def to_dict(self) -> dict:
        return {
            "spot": self.spot if present(self.spot) else str(FEED_REQUIRED),
            "gamma_regime": self.gamma.regime.value,
            "levels": [l.to_dict(self.spot) for l in self.levels],
            "expected_move": {
                "one_sigma": self.expected_move.em_1sigma if present(self.expected_move.em_1sigma) else str(FEED_REQUIRED),
                "upper": self.expected_move.upper if present(self.expected_move.upper) else str(FEED_REQUIRED),
                "lower": self.expected_move.lower if present(self.expected_move.lower) else str(FEED_REQUIRED),
                "confidence": self.expected_move.confidence if present(self.expected_move.confidence) else str(FEED_REQUIRED),
            },
            "trade_map": [{"condition": t.condition, "implication": t.implication,
                           "regime": t.regime_hint} for t in self.trade_map],
            "ranked": [{"rank": i + 1, "kind": r.level.kind.value,
                        "price": r.level.price, "importance": r.importance}
                       for i, r in enumerate(self.ranked)],
        }


# --------------------------------------------------------------------------- #
# Demo with a fake provider (proves end-to-end + FEED_REQUIRED discipline)
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    class FakeMD:
        def previous_session(self): return {"open": 7405, "high": 7442, "low": 7398, "close": 7430, "settlement": 7431}
        def overnight_bars(self):
            return [Bar(7430, 7438, 7425, 7433, v=1200), Bar(7433, 7440, 7429, 7436, v=1500)]
        def opening_bars(self):
            base = 7436
            return [Bar(base + i*0.1, base + i*0.1 + 3, base + i*0.1 - 3, base + i*0.1 + 1, v=800)
                    for i in range(60)]
        def spot(self): return 7455.0
        def atm_straddle(self): return 58.0
        def atm_iv(self): return 0.14
        def time_to_close_frac(self): return 1/252
        def atr(self, n=14): return 62.0
        def avg_daily_range(self, n=20): return 55.0

    class FakeGamma:
        def levels(self): return {"gamma_flip": 7440, "zero_gamma": 7438, "call_wall": 7500,
                                  "put_wall": 7400, "hi_gamma": 7450, "lo_gamma": 7350,
                                  "vol_trigger": 7420}
        def dealer_position(self): return GammaRegime.LONG_GAMMA
        def dealer_delta(self): return FEED_REQUIRED   # provider didn't return it -> stays absent

    class FakeVP:
        def levels(self): return {"dev_poc": 7448, "prev_poc": 7425, "comp_poc": 7410,
                                  "vah": 7460, "val": 7435, "comp_vah": 7470, "comp_val": 7395,
                                  "hvns": [7448, 7410], "lvns": [7475], "naked_pocs": [7385],
                                  "virgin_pocs": []}

    dkl = DailyKeyLevels.build(FakeMD(), FakeGamma(), FakeVP())
    print(render_brief_sections(dkl.spot, dkl.levels, dkl.gamma, dkl.expected_move,
                                dkl.trade_map, dkl.ranked))
    rc = build_risk_context(dkl.spot, dkl.levels, dkl.expected_move,
                            bias="bullish", regime="mean_reversion")
    print("\nRISK GATE:", "cap", rc.confidence_cap, "| block_high_conviction", rc.block_high_conviction,
          "| missing", rc.missing or "none",
          "| nearest gamma", rc.nearest_gamma.label if rc.nearest_gamma else None)

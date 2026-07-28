"""
APEX 46 — Institutional Decision Intelligence: typed contracts.

Location: engine/common/decision_contract.py

This module defines the *primitive* layer that the synthesis engines
(Consensus, Conviction, Decision) consume. It intentionally contains
data structures + deterministic aggregation only. It performs NO network
I/O (per the APEX rule that engines never fetch their own data) and holds
NO learned parameters — the two things that must be learned/injected are:

  1. independence weights for Consensus (decorrelation)
  2. the raw->calibrated map for Conviction

Both enter as arguments so they can be sourced from the ledger / learning
family and swapped without touching this contract.

Design decisions worth remembering (they encode the five critiques that
motivated APEX 46):

  * ABSTAIN != NEUTRAL. NEUTRAL means "I have a read and it's balanced."
    ABSTAIN means "I have no usable read" (no setup, or stale data). A
    NEUTRAL vote participates in consensus; an ABSTAIN vote does not.
  * FRESHNESS can force abstention. A vote past its TTL contributes 0 and
    is treated as abstaining, so conviction degrades gracefully instead of
    trusting stale inputs at full weight.
  * CONSENSUS exposes raw_count vs effective agreement. Correlated engines
    are down-weighted so "5 of 6 agree" cannot masquerade as five
    independent votes.
  * CONVICTION carries a calibration hook and a REQUIRED missing-evidence
    list. An uncalibrated conviction is flagged as such.
  * THESIS + INVALIDATION is a stateful, monitored object — the thing that
    turns a score into a defensible decision.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Mapping, Optional


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #

class Direction(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"

    @property
    def sign(self) -> int:
        return {"bullish": 1, "bearish": -1, "neutral": 0}[self.value]


class AcceptanceState(Enum):
    """Formalized auction acceptance vocabulary (brief §5)."""
    ACCEPTED = "accepted"
    WEAK_ACCEPTANCE = "weak_acceptance"
    TEMPORARY_ACCEPTANCE = "temporary_acceptance"
    REJECTED = "rejected"
    BALANCE = "balance"
    INITIATIVE_BUYING = "initiative_buying"
    INITIATIVE_SELLING = "initiative_selling"


class FailedBreakQuality(Enum):
    """Adam-Mancini-style failed breakdown/breakout tiers."""
    NONE = "none"
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    INSTITUTIONAL = "institutional"


class DecisionAction(Enum):
    WAIT = "wait"
    WATCH = "watch"
    PREPARE = "prepare"
    ACT = "act"


class ThesisState(Enum):
    FORMING = "forming"
    ACTIVE = "active"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"
    REALIZED = "realized"


# --------------------------------------------------------------------------- #
# Per-engine vote (the input primitive)
# --------------------------------------------------------------------------- #

def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


@dataclass
class EngineVote:
    """One engine's read for a single scan.

    strength, confidence, freshness are all 0..1.
      strength   : magnitude of the *directional* read (how far, not how sure)
      confidence : the engine's self-assessed reliability of THIS read
      as_of/ttl  : freshness is derived from data age, not asserted
      abstain    : explicit "no usable read" — distinct from NEUTRAL
    """
    engine: str
    direction: Direction = Direction.NEUTRAL
    strength: float = 0.0
    confidence: float = 0.0
    as_of: float = field(default_factory=time.time)
    ttl_s: Optional[float] = None          # None => no time decay
    abstain: bool = False
    reasons: list[str] = field(default_factory=list)   # provenance / "why"

    def freshness(self, now: Optional[float] = None) -> float:
        """1.0 when brand new, decaying linearly to 0.0 at ttl_s."""
        if self.ttl_s is None:
            return 1.0
        now = time.time() if now is None else now
        age = max(0.0, now - self.as_of)
        if self.ttl_s <= 0:
            return 0.0
        return _clamp01(1.0 - age / self.ttl_s)

    def is_stale(self, now: Optional[float] = None) -> bool:
        return self.freshness(now) <= 0.0

    def effective_abstain(self, now: Optional[float] = None) -> bool:
        """Freshness can force abstention."""
        return self.abstain or self.is_stale(now)

    def signed_strength(self, now: Optional[float] = None) -> float:
        """Direction-signed contribution, scaled by confidence AND freshness.

        Returns 0.0 for abstaining/stale/neutral votes. This is the scalar
        Consensus and Conviction actually aggregate.
        """
        if self.effective_abstain(now):
            return 0.0
        return (
            self.direction.sign
            * _clamp01(self.strength)
            * _clamp01(self.confidence)
            * self.freshness(now)
        )


# --------------------------------------------------------------------------- #
# Consensus (decorrelation-aware agreement)
# --------------------------------------------------------------------------- #

@dataclass
class ConsensusResult:
    dominant: Direction
    participating: int                 # engines with a usable read
    abstaining: list[str]
    raw_long: int                      # naive counts (the misleading number)
    raw_short: int
    raw_neutral: int
    weighted_long: float               # decorrelated, freshness/conf-scaled
    weighted_short: float
    effective_votes: float             # independent-weight sum on dominant side
    total_weight: float                # independent-weight sum, all participants
    net_signed: float
    agreement_ratio: float             # 0..1 : how lopsided the dominant side is
    weights: dict[str, float] = field(default_factory=dict)

    @property
    def raw_agreement_ratio(self) -> float:
        """The naive ratio, kept ONLY so the overstatement stays visible."""
        total = self.raw_long + self.raw_short + self.raw_neutral
        if total == 0:
            return 0.0
        return max(self.raw_long, self.raw_short) / total

    @property
    def redundancy(self) -> float:
        """How much the raw count overstates independent agreement (>=0).

        e.g. 5 correlated engines carrying total weight ~1.6 -> ~0.68.
        """
        raw_dom = max(self.raw_long, self.raw_short)
        if raw_dom == 0:
            return 0.0
        return _clamp01(1.0 - self.effective_votes / raw_dom)

    @classmethod
    def from_votes(
        cls,
        votes: list[EngineVote],
        weights: Optional[Mapping[str, float]] = None,
        now: Optional[float] = None,
        eps: float = 1e-6,
    ) -> "ConsensusResult":
        """Aggregate votes into a decorrelated consensus.

        `weights` maps engine name -> independence weight (default 1.0).
        Correlated engines should be given weights that sum toward a single
        vote so their agreement is not counted multiple times. These weights
        come from the learning family (historical co-firing), NOT from here.
        """
        w = dict(weights or {})
        abstaining, participating = [], []
        raw_long = raw_short = raw_neutral = 0
        wl = ws = 0.0
        total_weight = 0.0
        net = 0.0

        for v in votes:
            if v.effective_abstain(now):
                abstaining.append(v.engine)
                continue
            participating.append(v)
            gw = w.get(v.engine, 1.0)
            total_weight += gw
            ss = v.signed_strength(now)
            net += gw * ss
            if v.direction is Direction.BULLISH:
                raw_long += 1
                wl += gw * abs(ss)
            elif v.direction is Direction.BEARISH:
                raw_short += 1
                ws += gw * abs(ss)
            else:
                raw_neutral += 1

        if net > eps:
            dominant = Direction.BULLISH
        elif net < -eps:
            dominant = Direction.BEARISH
        else:
            dominant = Direction.NEUTRAL

        # effective independent votes on the dominant side
        eff = 0.0
        for v in participating:
            if v.direction is dominant and dominant is not Direction.NEUTRAL:
                eff += w.get(v.engine, 1.0)

        dom_weight = wl if dominant is Direction.BULLISH else ws if dominant is Direction.BEARISH else 0.0
        denom = wl + ws
        agreement = _clamp01(dom_weight / denom) if denom > 0 else 0.0

        return cls(
            dominant=dominant,
            participating=len(participating),
            abstaining=abstaining,
            raw_long=raw_long,
            raw_short=raw_short,
            raw_neutral=raw_neutral,
            weighted_long=wl,
            weighted_short=ws,
            effective_votes=eff,
            total_weight=total_weight,
            net_signed=net,
            agreement_ratio=agreement,
            weights=w,
        )


# --------------------------------------------------------------------------- #
# Conviction (calibrated final gate)
# --------------------------------------------------------------------------- #

@dataclass
class ConvictionResult:
    """Conviction on the 0..100 scale (aligned with ICI).

    raw is the constructed blend; calibrated is what a monitored map turns
    raw into so that "80" actually means ~80% realized. `calibrated_flag`
    tells the caller whether a real calibrator was applied — an uncalibrated
    conviction must never be silently trusted as if it were calibrated.
    """
    raw: float
    calibrated: float
    calibrated_flag: bool
    components: dict[str, float]         # factor -> contribution (0..1)
    missing: list[str]                   # REQUIRED evidence-gap output
    reliability: Optional[float] = None  # realized hit-rate for this bucket, from ledger
    notes: list[str] = field(default_factory=list)

    @classmethod
    def build(
        cls,
        components: Mapping[str, Optional[float]],
        weights: Optional[Mapping[str, float]] = None,
        calibrator: Optional[Callable[[float], float]] = None,
        reliability: Optional[float] = None,
    ) -> "ConvictionResult":
        """Blend conviction factors, then calibrate.

        `components` are the factors from the brief: liquidity, auction,
        dealer, order_flow, execution, narrative, breadth, freshness,
        consensus. A None value means the factor is MISSING (its engine
        abstained/was stale) and is recorded in `missing`, not treated as 0.
        """
        w = dict(weights or {})
        present, missing = {}, []
        for name, val in components.items():
            if val is None:
                missing.append(name)
            else:
                present[name] = _clamp01(val)

        if present:
            num = sum(present[k] * w.get(k, 1.0) for k in present)
            den = sum(w.get(k, 1.0) for k in present)
            raw = 100.0 * (num / den) if den > 0 else 0.0
        else:
            raw = 0.0

        if calibrator is not None:
            calibrated = float(calibrator(raw))
            flag = True
        else:
            calibrated = raw
            flag = False

        notes = []
        if not flag:
            notes.append("UNCALIBRATED: raw==calibrated; do not size off this yet.")
        if missing:
            notes.append(f"missing factors: {', '.join(missing)}")

        return cls(
            raw=round(raw, 2),
            calibrated=round(calibrated, 2),
            calibrated_flag=flag,
            components=present,
            missing=missing,
            reliability=reliability,
            notes=notes,
        )


# --------------------------------------------------------------------------- #
# Thesis + invalidation (the stateful centerpiece)
# --------------------------------------------------------------------------- #

class TriggerKind(Enum):
    PRICE_LEVEL = "price_level"
    DELTA = "delta"
    VOLUME = "volume"
    TIME = "time"
    ACCEPTANCE = "acceptance"
    GAMMA = "gamma"
    CUSTOM = "custom"


@dataclass
class InvalidationTrigger:
    """A single monitored condition that would kill the thesis.

    `predicate` is evaluated against a live context Mapping each refresh. If
    None, the trigger is monitored externally and `triggered` is set by the
    monitor. Keep predicates pure and cheap.
    """
    label: str
    kind: TriggerKind = TriggerKind.CUSTOM
    params: dict = field(default_factory=dict)
    predicate: Optional[Callable[[Mapping], bool]] = None
    triggered: bool = False
    triggered_at: Optional[float] = None

    def evaluate(self, context: Mapping, now: Optional[float] = None) -> bool:
        if self.triggered:
            return True
        if self.predicate is not None and self.predicate(context):
            self.triggered = True
            self.triggered_at = time.time() if now is None else now
        return self.triggered


@dataclass
class Thesis:
    """A living directional thesis with explicit invalidation.

    supporting/contradicting are recomputed from the current vote set on each
    refresh, so the object always answers 'who agrees right now?' — not just
    'who agreed at entry?'.
    """
    thesis_id: str
    side: Direction
    entry_evidence: list[str] = field(default_factory=list)
    key_levels: dict = field(default_factory=dict)
    invalidation: list[InvalidationTrigger] = field(default_factory=list)
    supporting: list[str] = field(default_factory=list)
    contradicting: list[str] = field(default_factory=list)
    state: ThesisState = ThesisState.FORMING
    created_at: float = field(default_factory=time.time)

    def refresh(self, votes: list[EngineVote], now: Optional[float] = None) -> None:
        """Recompute supporting/contradicting from current votes."""
        self.supporting, self.contradicting = [], []
        for v in votes:
            if v.effective_abstain(now) or v.direction is Direction.NEUTRAL:
                continue
            if v.direction is self.side:
                self.supporting.append(v.engine)
            else:
                self.contradicting.append(v.engine)
        if self.state in (ThesisState.FORMING, ThesisState.ACTIVE):
            self.state = ThesisState.ACTIVE if self.supporting else ThesisState.FORMING

    def check_invalidation(self, context: Mapping, now: Optional[float] = None) -> bool:
        fired = any(t.evaluate(context, now) for t in self.invalidation)
        if fired:
            self.state = ThesisState.INVALIDATED
        return fired

    @property
    def is_invalidated(self) -> bool:
        return self.state is ThesisState.INVALIDATED

    def evidence_gaps(self, all_engines: list[str]) -> list[str]:
        """Engines that are neither supporting nor contradicting — the
        silent set whose read we're missing."""
        seen = set(self.supporting) | set(self.contradicting)
        return [e for e in all_engines if e not in seen]


# --------------------------------------------------------------------------- #
# Decision (the unified object)
# --------------------------------------------------------------------------- #

@dataclass
class DecisionThresholds:
    """Gates for action. Defaults are placeholders — CALIBRATE against the
    ledger before trusting them."""
    act_conviction: float = 75.0
    prepare_conviction: float = 60.0
    watch_conviction: float = 45.0
    act_effective_votes: float = 3.0      # decorrelated, not raw count
    act_agreement: float = 0.66
    min_participating: int = 4
    require_calibrated_to_act: bool = True


@dataclass
class Decision:
    action: DecisionAction
    consensus: ConsensusResult
    conviction: ConvictionResult
    thesis: Optional[Thesis]
    rationale: str
    created_at: float = field(default_factory=time.time)

    @property
    def missing_evidence(self) -> list[str]:
        gaps = list(self.conviction.missing)
        gaps += [e for e in self.consensus.abstaining if e not in gaps]
        return gaps

    def provenance(self) -> dict:
        return {
            "dominant": self.consensus.dominant.value,
            "effective_votes": round(self.consensus.effective_votes, 3),
            "raw_dominant_count": max(self.consensus.raw_long, self.consensus.raw_short),
            "redundancy": round(self.consensus.redundancy, 3),
            "agreement_ratio": round(self.consensus.agreement_ratio, 3),
            "conviction_calibrated": self.conviction.calibrated,
            "conviction_is_calibrated": self.conviction.calibrated_flag,
            "reliability": self.conviction.reliability,
            "missing": self.missing_evidence,
            "thesis_state": self.thesis.state.value if self.thesis else None,
        }

    @classmethod
    def build(
        cls,
        consensus: ConsensusResult,
        conviction: ConvictionResult,
        thesis: Optional[Thesis] = None,
        thresholds: Optional[DecisionThresholds] = None,
    ) -> "Decision":
        t = thresholds or DecisionThresholds()

        # Hard vetoes first.
        if thesis is not None and thesis.is_invalidated:
            return cls(DecisionAction.WAIT, consensus, conviction, thesis,
                       "thesis invalidated -> stand down")
        if consensus.participating < t.min_participating:
            return cls(DecisionAction.WAIT, consensus, conviction, thesis,
                       f"insufficient participation "
                       f"({consensus.participating}/{t.min_participating}); "
                       f"missing={conviction.missing}")

        c = conviction.calibrated
        can_act = (
            c >= t.act_conviction
            and consensus.effective_votes >= t.act_effective_votes
            and consensus.agreement_ratio >= t.act_agreement
            and (conviction.calibrated_flag or not t.require_calibrated_to_act)
        )
        if can_act:
            action = DecisionAction.ACT
        elif c >= t.prepare_conviction:
            action = DecisionAction.PREPARE
        elif c >= t.watch_conviction:
            action = DecisionAction.WATCH
        else:
            action = DecisionAction.WAIT

        rationale = (
            f"{consensus.dominant.value} | conviction={c} "
            f"({'cal' if conviction.calibrated_flag else 'RAW'}) | "
            f"eff_votes={consensus.effective_votes:.2f} of "
            f"{max(consensus.raw_long, consensus.raw_short)} raw "
            f"(redundancy={consensus.redundancy:.2f}) | "
            f"agree={consensus.agreement_ratio:.2f}"
        )
        if conviction.missing:
            rationale += f" | missing={conviction.missing}"
        return cls(action, consensus, conviction, thesis, rationale)


# --------------------------------------------------------------------------- #
# Smoke test / usage example
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    now = time.time()

    # Two of these (gamma/flow) are deliberately correlated; execution is
    # stale (past TTL -> forced abstain); breadth abstains explicitly.
    votes = [
        EngineVote("liquidity", Direction.BULLISH, 0.7, 0.8, now, ttl_s=120,
                   reasons=["absorption at value low"]),
        EngineVote("gamma", Direction.BULLISH, 0.6, 0.7, now, ttl_s=120),
        EngineVote("order_flow", Direction.BULLISH, 0.65, 0.75, now, ttl_s=120),
        EngineVote("auction", Direction.BULLISH, 0.55, 0.6, now, ttl_s=120,
                   reasons=["acceptance above 7506"]),
        EngineVote("narrative", Direction.NEUTRAL, 0.0, 0.5, now, ttl_s=300),
        EngineVote("execution", Direction.BEARISH, 0.5, 0.6,
                   now - 999, ttl_s=120),           # stale -> abstains
        EngineVote("breadth", abstain=True),         # explicit no-read
    ]

    # gamma & order_flow historically co-fire with liquidity -> share weight.
    indep_weights = {"liquidity": 1.0, "gamma": 0.4, "order_flow": 0.4, "auction": 1.0}

    consensus = ConsensusResult.from_votes(votes, weights=indep_weights, now=now)

    conviction = ConvictionResult.build(
        components={
            "liquidity": 0.7, "auction": 0.55, "dealer": 0.6,
            "order_flow": 0.65, "execution": None,   # missing (stale)
            "narrative": 0.5, "breadth": None,        # missing (abstain)
            "freshness": 0.8, "consensus": consensus.agreement_ratio,
        },
        calibrator=None,   # no calibrator yet -> flagged UNCALIBRATED
    )

    thesis = Thesis(
        thesis_id="2026-07-29-long-7506",
        side=Direction.BULLISH,
        entry_evidence=["acceptance above 7506", "liquidity absorption"],
        key_levels={"support": 7506.0, "target": 7550.0},
        invalidation=[
            InvalidationTrigger(
                "lose 7506 on volume with delta rolling",
                TriggerKind.PRICE_LEVEL,
                params={"level": 7506.0, "side": "below"},
                predicate=lambda ctx: ctx.get("price", 9e9) < 7506.0
                and ctx.get("delta_rolling", False),
            ),
        ],
    )
    thesis.refresh(votes, now=now)
    thesis.check_invalidation({"price": 7512.0, "delta_rolling": False}, now=now)

    decision = Decision.build(consensus, conviction, thesis)

    print("ACTION:", decision.action.value)
    print("RATIONALE:", decision.rationale)
    print("RAW consensus:", f"{max(consensus.raw_long, consensus.raw_short)} of "
          f"{consensus.participating}", "->  EFFECTIVE:",
          round(consensus.effective_votes, 2),
          f"(redundancy {consensus.redundancy:.0%})")
    print("SUPPORTING:", thesis.supporting, "| CONTRADICTING:", thesis.contradicting)
    print("MISSING:", decision.missing_evidence)
    print("PROVENANCE:", decision.provenance())

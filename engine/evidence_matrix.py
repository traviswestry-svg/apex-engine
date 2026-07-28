"""
APEX 46 — Evidence Conflict Matrix.

Location: engine/common/evidence_matrix.py
Companion to decision_contract.py.

A consensus percentage collapses two very different low-conviction causes
into one number:

  * GENUINE_CONFLICT — engines with fresh reads actively disagree. The
    market is two-way; the correct response is patience / reduced size.
  * DATA_STARVED — conviction is low only because engines are abstaining or
    stale. This is a plumbing problem, not a market signal; fix the feed and
    do NOT read the thinness as two-sidedness.

The matrix disambiguates them, and — applying the same decorrelation
principle used in Consensus — it flags when dissent is coming from an
engine that normally reads *independently*, because that dissent is worth
far more than a redundant confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional

from decision_contract import Direction, EngineVote, ConsensusResult


class Bucket(Enum):
    BULL = "bull"
    BEAR = "bear"
    NEUTRAL = "neutral"
    ABSTAIN = "abstain"


class ConflictState(Enum):
    CONSENSUS = "consensus"                 # fresh engines agree, decent strength
    WEAK_SIGNAL = "weak_signal"             # coherent direction, low strength/conf
    PARTIAL_CONFLICT = "partial_conflict"   # dominant side but real weighted dissent
    GENUINE_CONFLICT = "genuine_conflict"   # fresh reads split ~evenly
    DATA_STARVED = "data_starved"           # abstain/stale dominate -> not a signal


@dataclass
class EvidenceRow:
    engine: str
    bucket: Bucket
    fresh: bool
    weight: float                 # independence weight
    strength_conf: float          # strength * confidence (0 if abstaining)


@dataclass
class EvidenceMatrix:
    rows: list[EvidenceRow]
    dominant: Direction
    state: ConflictState
    dissenters: list[str]
    independent_dissenters: list[str]   # dissent from normally-decorrelated engines
    stale: list[str]
    abstaining: list[str]
    weighted_support: float
    weighted_dissent: float
    diagnosis: str
    thresholds: dict = field(default_factory=dict)

    # ---- construction ---------------------------------------------------- #
    @classmethod
    def from_votes(
        cls,
        votes: list[EngineVote],
        consensus: ConsensusResult,
        now: Optional[float] = None,
        *,
        min_fresh_reads: int = 3,
        starved_abstain_frac: float = 0.5,
        conflict_band: tuple[float, float] = (0.40, 0.60),
        partial_dissent: float = 0.25,
        weak_strength: float = 0.35,
        independent_weight: float = 0.85,   # weight >= this => "independent" engine
    ) -> "EvidenceMatrix":
        weights = consensus.weights
        dominant = consensus.dominant

        rows: list[EvidenceRow] = []
        stale, abstaining = [], []
        w_bull = w_bear = 0.0
        fresh_directional = neutral_ct = 0
        dissenters, indep_dissenters = [], []

        for v in votes:
            fresh = not v.is_stale(now)
            gw = weights.get(v.engine, 1.0)
            sc = 0.0
            if v.effective_abstain(now):
                bucket = Bucket.ABSTAIN
                abstaining.append(v.engine)
                if not fresh:
                    stale.append(v.engine)
            elif v.direction is Direction.BULLISH:
                bucket, sc = Bucket.BULL, v.strength * v.confidence
                w_bull += gw * sc
                fresh_directional += 1
            elif v.direction is Direction.BEARISH:
                bucket, sc = Bucket.BEAR, v.strength * v.confidence
                w_bear += gw * sc
                fresh_directional += 1
            else:
                bucket = Bucket.NEUTRAL
                neutral_ct += 1
            rows.append(EvidenceRow(v.engine, bucket, fresh, gw, round(sc, 3)))

        # support vs dissent relative to the dominant side
        if dominant is Direction.BULLISH:
            support, dissent = w_bull, w_bear
            dissent_dir = Direction.BEARISH
        elif dominant is Direction.BEARISH:
            support, dissent = w_bear, w_bull
            dissent_dir = Direction.BULLISH
        else:
            support = dissent = 0.0
            dissent_dir = None

        for r in rows:
            is_dissent = (
                (dissent_dir is Direction.BEARISH and r.bucket is Bucket.BEAR)
                or (dissent_dir is Direction.BULLISH and r.bucket is Bucket.BULL)
            )
            if is_dissent:
                dissenters.append(r.engine)
                if r.weight >= independent_weight:
                    indep_dissenters.append(r.engine)

        total = len(votes)
        abstain_frac = (len(abstaining) / total) if total else 1.0
        mass = support + dissent
        dissent_ratio = (dissent / mass) if mass > 0 else 0.0
        avg_support_strength = (
            support / max(1e-9, sum(
                weights.get(r.engine, 1.0) for r in rows
                if (r.bucket is Bucket.BULL and dominant is Direction.BULLISH)
                or (r.bucket is Bucket.BEAR and dominant is Direction.BEARISH)
            ))
        )

        # ---- classify (order matters) ----------------------------------- #
        if fresh_directional < min_fresh_reads or abstain_frac >= starved_abstain_frac:
            state = ConflictState.DATA_STARVED
        elif dominant is Direction.NEUTRAL or conflict_band[0] <= dissent_ratio <= conflict_band[1]:
            state = ConflictState.GENUINE_CONFLICT
        elif dissent_ratio >= partial_dissent:
            state = ConflictState.PARTIAL_CONFLICT
        elif avg_support_strength < weak_strength:
            state = ConflictState.WEAK_SIGNAL
        else:
            state = ConflictState.CONSENSUS

        diagnosis = cls._diagnose(
            state, dominant, dissenters, indep_dissenters, stale, abstaining,
            dissent_ratio,
        )

        return cls(
            rows=rows, dominant=dominant, state=state,
            dissenters=dissenters, independent_dissenters=indep_dissenters,
            stale=stale, abstaining=abstaining,
            weighted_support=round(support, 3), weighted_dissent=round(dissent, 3),
            diagnosis=diagnosis,
            thresholds={
                "dissent_ratio": round(dissent_ratio, 3),
                "abstain_frac": round(abstain_frac, 3),
                "fresh_directional": fresh_directional,
            },
        )

    @staticmethod
    def _diagnose(state, dominant, dissenters, indep, stale, abstaining, dr) -> str:
        if state is ConflictState.DATA_STARVED:
            miss = sorted(set(stale) | set(abstaining))
            return (f"Low conviction is DATA-DRIVEN, not disagreement: "
                    f"{len(miss)} engine(s) stale/abstaining ({', '.join(miss)}). "
                    f"Fix inputs; do not read thinness as a two-way market.")
        if state is ConflictState.GENUINE_CONFLICT:
            base = (f"GENUINE CONFLICT: fresh engines split "
                    f"(dissent ratio {dr:.0%}). Market is two-way — patience / reduced size.")
            if indep:
                base += f" Dissent includes independent engine(s): {', '.join(indep)} (high signal)."
            return base
        if state is ConflictState.PARTIAL_CONFLICT:
            msg = (f"{dominant.value.upper()} lean with real dissent "
                   f"({dr:.0%}) from {', '.join(dissenters)}.")
            if indep:
                msg += f" Note: {', '.join(indep)} normally reads independently — weight it."
            return msg
        if state is ConflictState.WEAK_SIGNAL:
            return (f"Coherent {dominant.value} direction but weak strength/confidence — "
                    f"agreement without conviction.")
        return f"CONSENSUS: fresh engines agree {dominant.value} with adequate strength."

    # ---- rendering ------------------------------------------------------- #
    def to_table(self) -> str:
        def mark(cond: bool) -> str:
            return "✓" if cond else " "

        head = f"{'Engine':<12}{'Bull':^6}{'Bear':^6}{'Neut':^6}{'Abst':^6}{'Fresh':^7}"
        line = "-" * len(head)
        out = [head, line]
        for r in self.rows:
            out.append(
                f"{r.engine:<12}"
                f"{mark(r.bucket is Bucket.BULL):^6}"
                f"{mark(r.bucket is Bucket.BEAR):^6}"
                f"{mark(r.bucket is Bucket.NEUTRAL):^6}"
                f"{mark(r.bucket is Bucket.ABSTAIN):^6}"
                f"{('✓' if r.fresh else '✗'):^7}"
            )
        out.append(line)
        out.append(f"STATE: {self.state.value.upper()}")
        out.append(f"WHY:   {self.diagnosis}")
        return "\n".join(out)

    def to_dict(self) -> dict:
        return {
            "dominant": self.dominant.value,
            "state": self.state.value,
            "diagnosis": self.diagnosis,
            "dissenters": self.dissenters,
            "independent_dissenters": self.independent_dissenters,
            "stale": self.stale,
            "abstaining": self.abstaining,
            "weighted_support": self.weighted_support,
            "weighted_dissent": self.weighted_dissent,
            "metrics": self.thresholds,
            "rows": [
                {"engine": r.engine, "bucket": r.bucket.value,
                 "fresh": r.fresh, "weight": r.weight, "strength_conf": r.strength_conf}
                for r in self.rows
            ],
        }


# --------------------------------------------------------------------------- #
# Demo: same low consensus, two different causes -> two different diagnoses
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import time
    now = time.time()
    weights = {"liquidity": 1.0, "gamma": 0.4, "flow": 0.4, "auction": 1.0,
               "breadth": 1.0, "execution": 1.0}

    print("=== SCENARIO A: genuine disagreement (all fresh) ===")
    votes_a = [
        EngineVote("liquidity", Direction.BULLISH, 0.7, 0.8, now, ttl_s=120),
        EngineVote("flow", Direction.BULLISH, 0.65, 0.75, now, ttl_s=120),
        EngineVote("gamma", Direction.BEARISH, 0.7, 0.8, now, ttl_s=120),
        EngineVote("auction", Direction.BEARISH, 0.75, 0.85, now, ttl_s=120),
        EngineVote("breadth", Direction.NEUTRAL, 0.0, 0.5, now, ttl_s=300),
        EngineVote("execution", Direction.BULLISH, 0.5, 0.6, now, ttl_s=120),
    ]
    con_a = ConsensusResult.from_votes(votes_a, weights=weights, now=now)
    mat_a = EvidenceMatrix.from_votes(votes_a, con_a, now=now)
    print(mat_a.to_table())

    print("\n=== SCENARIO B: same weak consensus, but it's missing data ===")
    votes_b = [
        EngineVote("liquidity", Direction.BULLISH, 0.7, 0.8, now, ttl_s=120),
        EngineVote("flow", Direction.BULLISH, 0.65, 0.75, now, ttl_s=120),
        EngineVote("gamma", Direction.BULLISH, 0.6, 0.7, now, ttl_s=120),
        EngineVote("auction", Direction.BULLISH, 0.55, 0.6, now - 999, ttl_s=120),  # stale
        EngineVote("breadth", abstain=True),                                          # no read
        EngineVote("execution", Direction.BEARISH, 0.5, 0.6, now - 999, ttl_s=120),   # stale
    ]
    con_b = ConsensusResult.from_votes(votes_b, weights=weights, now=now)
    mat_b = EvidenceMatrix.from_votes(votes_b, con_b, now=now)
    print(mat_b.to_table())

"""APEX 50.2 deterministic level analytics.

These scores are transparent heuristics, not calibrated win probabilities. They
replace misleading FEED_REQUIRED placeholders for fields that are internal APEX
analytics rather than provider data.
"""
from __future__ import annotations

from math import exp
from typing import Iterable

from .daily_key_levels import KeyLevel, LevelKind, present

_KIND_STRENGTH = {
    LevelKind.GAMMA_FLIP: .92, LevelKind.ZERO_GAMMA: .88,
    LevelKind.CALL_WALL: .86, LevelKind.PUT_WALL: .86,
    LevelKind.DEV_POC: .88, LevelKind.PREV_POC: .82, LevelKind.COMP_POC: .90,
    LevelKind.VAH: .76, LevelKind.VAL: .76, LevelKind.COMP_VAH: .82, LevelKind.COMP_VAL: .82,
    LevelKind.PDH: .78, LevelKind.PDL: .78, LevelKind.ON_HIGH: .70, LevelKind.ON_LOW: .70,
    LevelKind.HVN: .72, LevelKind.LVN: .66, LevelKind.LIQ_POOL: .74,
    LevelKind.EQ_HIGH: .70, LevelKind.EQ_LOW: .70, LevelKind.FVG: .62,
    LevelKind.SWING_HIGH: .60, LevelKind.SWING_LOW: .60,
    LevelKind.HI_GAMMA: .80, LevelKind.LO_GAMMA: .80,
    LevelKind.EM_UPPER: .68, LevelKind.EM_LOWER: .68,
}
_MAGNET_KINDS = {LevelKind.DEV_POC, LevelKind.PREV_POC, LevelKind.COMP_POC,
                 LevelKind.HVN, LevelKind.CALL_WALL, LevelKind.PUT_WALL,
                 LevelKind.GAMMA_FLIP, LevelKind.ZERO_GAMMA}
_REJECTION_KINDS = {LevelKind.PDH, LevelKind.PDL, LevelKind.ON_HIGH, LevelKind.ON_LOW,
                    LevelKind.VAH, LevelKind.VAL, LevelKind.LVN, LevelKind.CALL_WALL,
                    LevelKind.PUT_WALL, LevelKind.SWING_HIGH, LevelKind.SWING_LOW}


def enrich_level_analytics(spot, levels: Iterable[KeyLevel]) -> list[KeyLevel]:
    levels = list(levels)
    distances = [abs(float(l.price) - float(spot)) for l in levels
                 if present(l.price) and present(spot)]
    scale = (sorted(distances)[len(distances)//2] if distances else 25.0) or 25.0

    for level in levels:
        if not present(level.price):
            continue
        distance = abs(float(level.price) - float(spot)) if present(spot) else scale
        proximity = exp(-distance / max(scale, 1.0))
        base = _KIND_STRENGTH.get(level.kind, .55)
        observed = float(level.strength_score) if present(level.strength_score) else base
        strength = max(0.05, min(0.99, .70 * observed + .30 * proximity))

        reaction = .42 + .42 * strength
        if level.kind in _REJECTION_KINDS:
            reaction += .05
        reaction = max(.10, min(.93, reaction))

        # A strong nearby level is more likely to react and less likely to break
        # on first contact. This is a heuristic context score, not a forecast.
        break_prob = max(.07, min(.90, 1.0 - reaction + .12 * (1.0 - proximity)))
        reversal = max(.08, min(.88, reaction * (.78 if level.kind in _REJECTION_KINDS else .58)))
        magnet = max(.05, min(.96, (.55 * strength + .45 * proximity)
                              * (1.10 if level.kind in _MAGNET_KINDS else .88)))

        level.strength_score = round(strength, 3)
        level.reaction_prob = round(reaction, 3)
        level.break_prob = round(break_prob, 3)
        level.reversal_prob = round(reversal, 3)
        level.magnet_score = round(magnet, 3)
    return levels

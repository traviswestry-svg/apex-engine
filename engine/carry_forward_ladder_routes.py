"""HTTP surface for the Carry-Forward Levels Ladder.

Reshapes the already-computed Daily Key Levels ``structured`` payload (the same
object the Morning Brief is built from) into a spot-relative ladder. The route
does no provider I/O and never generates a brief — it reads whatever structured
levels the caller's ``structured_provider`` hands back, so it stays cheap enough
to hit on every dashboard refresh.
"""
from __future__ import annotations

from flask import jsonify, request

from .carry_forward_ladder import build_carry_forward_ladder


def register_carry_forward_ladder_routes(app, *, structured_provider):
    def _ladder():
        ticker = (request.args.get("ticker") or "SPX").strip().upper() or "SPX"
        structured, spot = ({}, None)
        try:
            provided = structured_provider(ticker) if callable(structured_provider) else None
            if isinstance(provided, tuple):
                structured, spot = (provided + (None, None))[:2]
            elif isinstance(provided, dict):
                structured = provided
        except Exception:
            structured, spot = ({}, None)
        return build_carry_forward_ladder(structured or {}, spot=spot)

    @app.get("/api/carry-forward-ladder")
    def carry_forward_ladder():
        return jsonify(_ladder())

    # Alias so either name works from the dashboard / bookmarks.
    @app.get("/api/levels-ladder")
    def levels_ladder():
        return jsonify(_ladder())

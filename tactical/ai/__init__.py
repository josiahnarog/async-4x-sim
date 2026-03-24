"""Tactical AI package.

Entry points:
    make_move_orders(enc, owner_id, profile, rng)     -> Encounter
    make_fire_orders(enc, owner_id, profile, rng)     -> Encounter
    make_squadron_orders(enc, owner_id, profile, rng) -> Encounter

Each function stages the appropriate orders for owner_id and returns
the updated Encounter.  The caller is responsible for committing.

Typical usage (full AI turn):
    enc = make_move_orders(enc, "B", rng=rng)
    enc, events = enc.commit_movement("B", rng)

    enc = make_fire_orders(enc, "B", rng=rng)
    enc, events = enc.commit_fire("B", rng)

    enc = make_squadron_orders(enc, "B", rng=rng)
    enc, events = enc.commit_squadron_orders("B", rng)
"""

from tactical.ai.profile import AIProfile, DEFAULT, EASY, HARD
from tactical.ai.ai_player import make_move_orders, make_fire_orders, make_squadron_orders

__all__ = [
    "AIProfile",
    "DEFAULT",
    "EASY",
    "HARD",
    "make_move_orders",
    "make_fire_orders",
    "make_squadron_orders",
]

"""Top-level AI player entry points.

Each function stages orders for one side and returns the updated Encounter.
The caller is responsible for committing orders after staging.

Typical usage for a fully AI-controlled turn:

    import random
    from tactical.ai import make_move_orders, make_fire_orders, make_squadron_orders, DEFAULT

    rng = random.Random(seed)

    enc = make_move_orders(enc, "B", DEFAULT, rng)
    enc, events = enc.commit_movement("B", rng)

    enc = make_fire_orders(enc, "B", DEFAULT, rng)
    enc, events = enc.commit_fire("B", rng)

    enc = make_squadron_orders(enc, "B", DEFAULT, rng)
    enc, events = enc.commit_squadron_orders("B", rng)
"""

from __future__ import annotations

import random

from tactical.encounter import Encounter
from tactical.ai.profile import AIProfile, DEFAULT as _DEFAULT
from tactical.ai.fire_ai import choose_fire_orders
from tactical.ai.move_ai import choose_move_orders
from tactical.ai.squadron_ai import choose_launch_orders, choose_squadron_orders


def make_move_orders(
    enc: Encounter,
    owner_id: str,
    profile: AIProfile = _DEFAULT,
    rng: random.Random | None = None,
) -> Encounter:
    """Stage movement and launch orders for all ships owned by owner_id.

    Launch orders are staged first (carrier launches squadrons before ships
    move, matching the resolution order in _resolve_movement).

    Returns the updated Encounter with all orders staged but not committed.
    """
    if rng is None:
        rng = random.Random()

    # Stage launch orders.
    for carrier_id, sq_id in choose_launch_orders(enc.battle, owner_id, profile, rng):
        try:
            enc = enc.stage_launch(owner_id, carrier_id, sq_id)
        except (ValueError, KeyError, PermissionError):
            pass

    # Stage ship movement orders.
    move_orders = choose_move_orders(
        enc.battle, owner_id, enc._mp_capacity, profile, rng
    )
    for ship_id, (dest, facing) in move_orders.items():
        try:
            enc = enc.stage_move(owner_id, ship_id, dest, facing)
        except (ValueError, KeyError, PermissionError):
            pass

    return enc


def make_fire_orders(
    enc: Encounter,
    owner_id: str,
    profile: AIProfile = _DEFAULT,
    rng: random.Random | None = None,
) -> Encounter:
    """Stage fire orders for all ships owned by owner_id.

    Ships with no legal target receive an explicit pass (will not fire).
    Ships whose stage_fire call raises ValueError (e.g. blind-spot edge case)
    also receive a pass rather than crashing.

    Returns the updated Encounter with all orders staged but not committed.
    """
    if rng is None:
        rng = random.Random()

    orders = choose_fire_orders(enc.battle, owner_id, profile, rng)
    for ship_id, order in orders.items():
        if order is None:
            try:
                enc = enc.pass_fire(owner_id, ship_id)
            except (ValueError, KeyError, PermissionError):
                pass
        else:
            try:
                enc = enc.stage_fire(owner_id, ship_id, order.target_id)
            except (ValueError, KeyError, PermissionError):
                # Fallback: explicit pass so the ship doesn't silently skip.
                try:
                    enc = enc.pass_fire(owner_id, ship_id)
                except (ValueError, KeyError, PermissionError):
                    pass

    return enc


def make_squadron_orders(
    enc: Encounter,
    owner_id: str,
    profile: AIProfile = _DEFAULT,
    rng: random.Random | None = None,
) -> Encounter:
    """Stage COMBAT_SMALL orders for all deployed squadrons owned by owner_id.

    Squadrons with no suitable order hold position (no order staged).
    Any order that fails validation is silently skipped.

    Returns the updated Encounter with all orders staged but not committed.
    """
    if rng is None:
        rng = random.Random()

    orders = choose_squadron_orders(enc.battle, owner_id, profile, rng)
    for sq_id, order in orders.items():
        try:
            enc = enc.stage_squadron_order(owner_id, sq_id, order)
        except (ValueError, KeyError, PermissionError):
            pass

    return enc

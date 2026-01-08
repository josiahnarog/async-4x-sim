from __future__ import annotations
from typing import Tuple

INIT_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}


def init_rank(letter: str) -> int:
    return INIT_ORDER.get(letter, 99)


def volley_sort_key(g) -> Tuple[int, int, str]:
    return (init_rank(getattr(g, "initiative", "Z")), -int(getattr(g, "tactics", 0)), str(g.group_id))


def ensure_damage_attr(g) -> None:
    if not hasattr(g, "damage"):
        setattr(g, "damage", 0)


def apply_hits_to_group(g, hits: int):
    """
    Apply hits to a UnitGroup modeled as count identical ships with hull.
    Tracks partial hull on g.damage.
    Returns (ships_destroyed, remaining_hits_unused).
    """
    ensure_damage_attr(g)
    destroyed = 0
    hull = max(1, int(g.hull))

    while hits > 0 and g.count > 0:
        g.damage += 1
        hits -= 1
        if g.damage >= hull:
            g.count -= 1
            destroyed += 1
            g.damage = 0

    return destroyed, hits

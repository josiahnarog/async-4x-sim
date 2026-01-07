from __future__ import annotations
from typing import Callable, Sequence, Optional
def choose_target(attacker, enemies):
    """
    Returns a UnitGroup to target.
    """
    raise NotImplementedError


# A policy takes (attacker_group, enemy_groups) and returns the chosen enemy group (or None).
TargetingPolicy = Callable[[object, Sequence[object]], Optional[object]]


def focus_fire(attacker, enemies):
    """
    Focus Fire (intelligent):
      1) lowest remaining hull points on the current ship (i.e., easiest to finish)
      2) lowest defense
      3) highest attack
      4) stable tiebreaker: group_id
    Assumes each group has: hull, defense, attack, group_id, and optionally damage.
    """
    if not enemies:
        return None

    def remaining_hull(g) -> int:
        dmg = getattr(g, "damage", 0)
        return max(0, int(g.hull) - int(dmg))

    def key(g):
        # Note: we want highest attack last, so use -attack in ascending sort
        return (remaining_hull(g), int(g.defense), -int(g.attack), str(g.group_id))

    return min(enemies, key=key)


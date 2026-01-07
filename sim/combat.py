from __future__ import annotations
from dataclasses import dataclass
from collections import defaultdict
import random
from typing import Dict, List, Set, Tuple, Optional

from sim.hexgrid import Hex
from sim.units import UnitGroup, PlayerID

INIT_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}

@dataclass
class Battle:
    location: Hex
    owners: Set  # set[PlayerID] but keep generic to avoid circular typing
    groups_by_owner: Dict  # Dict[PlayerID, List[UnitGroup]]


def collect_battles(game, combat_sites: Set[Hex]) -> List[Battle]:
    battles: List[Battle] = []

    for hx in sorted(combat_sites, key=lambda h: (h.q, h.r)):
        groups = game.groups_at(hx)
        owners = {g.owner for g in groups}
        if len(owners) < 2:
            continue

        groups_by_owner = {}
        for g in groups:
            groups_by_owner.setdefault(g.owner, []).append(g)

        battles.append(Battle(location=hx, owners=owners, groups_by_owner=groups_by_owner))

    return battles


def firing_key(g: UnitGroup) -> tuple[int, int, str]:
    """
    Lower is earlier:
      initiative bucket (A earliest)
      -tactics (higher tactics earlier within bucket)
      stable tie-breaker (group_id)
    """
    return (INIT_ORDER[g.initiative], -g.tactics, g.group_id)
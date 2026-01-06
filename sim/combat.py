from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Set

from sim.hexgrid import Hex


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

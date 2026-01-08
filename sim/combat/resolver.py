from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Set
import random

from sim.combat.utils import volley_sort_key, init_rank, ensure_damage_attr, apply_hits_to_group, INIT_ORDER
from sim.hexgrid import Hex
from sim.units import UnitGroup


@dataclass
class Battle:
    location: Hex
    owners: Set  # set[PlayerID] but keep generic to avoid circular typing
    groups_by_owner: Dict  # Dict[PlayerID, List[UnitGroup]]


from dataclasses import dataclass
from typing import Dict, List, Set
from sim.hexgrid import Hex


from dataclasses import dataclass
from typing import Dict, List, Set
from sim.hexgrid import Hex

@dataclass(frozen=True)
class Battle:
    location: Hex
    owners: List          # combatant owners (deterministic order)
    groups_by_owner: Dict # all groups present, including noncombatants


def collect_battles(game, combat_sites: Set[Hex]) -> List[Battle]:
    battles: List[Battle] = []

    for hx in sorted(combat_sites, key=lambda h: (h.q, h.r)):
        groups = list(game.groups_at(hx))
        if not groups:
            continue

        groups_by_owner: Dict = {}
        for g in groups:
            groups_by_owner.setdefault(g.owner, []).append(g)

        # Only owners with at least one COMBATANT count for triggering a battle
        combatant_owners = {
            owner
            for owner, gs in groups_by_owner.items()
            if any(getattr(x.unit_type, "is_combatant", True) for x in gs)
        }

        if len(combatant_owners) < 2:
            continue

        battles.append(Battle(location=hx, owners=combatant_owners, groups_by_owner=groups_by_owner))

    return battles




def firing_key(g: UnitGroup) -> tuple[int, int, str]:
    """
    Lower is earlier:
      initiative bucket (A earliest)
      -tactics (higher tactics earlier within bucket)
      stable tie-breaker (group_id)
    """
    return (INIT_ORDER[g.initiative], -g.tactics, g.group_id)

def resolve_combat(game, attacker_owner, hex_) -> List[str]:
    """
    Multi-round D10 combat with initiative+tactics volleys until <=1 owner remains.

    game must provide:
      - groups_at(hex_) -> list[UnitGroup]
      - get_group(group_id) -> UnitGroup|None
      - remove_group(group_id)
      - reveal_hex_to_players(hex_, viewers=[...]) -> list[str]|None
      - (optional) targeting_policy(attacker, enemies)
      - (optional) turn_number for deterministic RNG seeding
    """
    events: List[str] = []

    def alive_groups() -> List:
        return [g for g in game.groups_at(hex_) if getattr(g, "count", 0) > 0]

    def owners_present(gs: List) -> Set:
        return {g.owner for g in gs}

    groups_now = alive_groups()
    owners_now = owners_present(groups_now)
    if len(owners_now) < 2:
        events.append(f"Combat at {hex_} had no opposing sides.")
        return events

    # Reveal once at combat start
    reveal_events = game.reveal_hex_to_players(hex_, viewers=list(owners_now)) or []
    events.extend(reveal_events)

    # Deterministic RNG per battle (debuggable)
    seed_material = f"{getattr(game, 'turn_number', 0)}|{hex_.q},{hex_.r}|{str(attacker_owner)}"
    rng = random.Random(seed_material)

    def choose_target(attacker, enemies) -> Optional[object]:
        pol = getattr(game, "targeting_policy", None)
        if callable(pol):
            return pol(attacker, enemies)

        # fallback: remaining hull, then lowest defense, then highest attack, then id
        def remaining_hull(g) -> int:
            ensure_damage_attr(g)
            return max(0, int(g.hull) - int(g.damage))

        return min(enemies, key=lambda g: (remaining_hull(g), int(g.defense), -int(g.attack), str(g.group_id)))

    max_rounds = 50
    round_num = 0

    while True:
        groups_now = alive_groups()
        owners_now = owners_present(groups_now)
        if len(owners_now) < 2:
            break

        round_num += 1
        if round_num > max_rounds:
            events.append(f"Combat at {hex_} aborted after {max_rounds} rounds (safety stop).")
            break

        events.append(f"Round {round_num} begins.")

        roster: Set[str] = {g.group_id for g in groups_now}

        volley_num = 0
        while True:
            # Remove dead from roster
            roster = {gid for gid in roster if game.get_group(gid) is not None and game.get_group(gid).count > 0}
            if not roster:
                break

            # If combat ended mid-round, stop
            groups_now = alive_groups()
            owners_now = owners_present(groups_now)
            if len(owners_now) < 2:
                roster.clear()
                break

            roster_groups = [game.get_group(gid) for gid in roster]
            roster_groups = [g for g in roster_groups if g is not None and g.count > 0]
            roster_groups.sort(key=volley_sort_key)

            g0 = roster_groups[0]
            next_key = (init_rank(g0.initiative), -int(getattr(g0, "tactics", 0)))

            volley_groups = [
                g for g in roster_groups
                if (init_rank(g.initiative), -int(getattr(g, "tactics", 0))) == next_key
            ]

            for g in volley_groups:
                roster.discard(g.group_id)

            volley_num += 1
            init_letter = volley_groups[0].initiative
            tactics_level = int(getattr(volley_groups[0], "tactics", 0))
            events.append(f"  Volley {volley_num}: Initiative {init_letter}, Tactics {tactics_level} ({len(volley_groups)} group(s))")

            snapshot = alive_groups()
            hits_map: Dict[str, int] = defaultdict(int)

            for attacker in volley_groups:
                attacker_live = game.get_group(attacker.group_id)
                if attacker_live is None or attacker_live.count <= 0:
                    continue
                attacker = attacker_live

                enemies = [g for g in snapshot if g.owner != attacker.owner and g.count > 0]
                if not enemies:
                    continue

                target = choose_target(attacker, enemies)
                if target is None:
                    continue

                to_hit = max(1, int(attacker.attack) - int(target.defense))

                hits = 0
                for _ in range(int(attacker.count)):
                    roll = rng.randint(1, 10)
                    if roll >= to_hit:
                        hits += 1

                hits_map[target.group_id] += hits
                events.append(
                    f"    {attacker.group_id} -> {target.group_id}: {attacker.count} shot(s), "
                    f"to-hit {to_hit} on d10, hits={hits}"
                )

            for target_id, hits in hits_map.items():
                target = game.get_group(target_id)
                if target is None or target.count <= 0:
                    continue

                before_count = target.count
                ensure_damage_attr(target)
                before_damage = target.damage

                destroyed, _unused = apply_hits_to_group(target, int(hits))
                events.append(
                    f"    {target.group_id} takes {hits} hit(s): ships {before_count}->{target.count}, "
                    f"damage {before_damage}->{target.damage}"
                )

                if target.count <= 0:
                    events.append(f"    {target.group_id} destroyed.")
                    game.remove_group(target.group_id)

        events.append(f"Round {round_num} ends.")

    events.append(f"Combat at {hex_} ends.")
    return events

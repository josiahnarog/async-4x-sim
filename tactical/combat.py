from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from sim.hexgrid import Hex
from tactical.battle_state import BattleState, ShipID
from tactical.weapons import WEAPONS, WeaponType, WeaponSpec


class RNG(Protocol):
    def randint(self, a: int, b: int) -> int: ...


def hex_distance(a: Hex, b: Hex) -> int:
    dq = abs(a.q - b.q)
    dr = abs(a.r - b.r)
    ds = abs((a.q + a.r) - (b.q + b.r))
    return max(dq, dr, ds)


@dataclass(frozen=True, slots=True)
class FireEvent:
    attacker_id: ShipID
    target_id: ShipID
    weapon: WeaponType
    range: int
    roll: int
    to_hit: Optional[int]
    hit: bool
    raw_damage: int


def resolve_large_fire(
    battle: BattleState,
    *,
    attacker_id: ShipID,
    target_id: ShipID,
    weapon: WeaponType,
    rng: RNG,
) -> tuple[BattleState, FireEvent]:
    if attacker_id not in battle.ships:
        raise KeyError(f"Unknown attacker_id: {attacker_id!r}")
    if target_id not in battle.ships:
        raise KeyError(f"Unknown target_id: {target_id!r}")

    attacker = battle.ships[attacker_id]
    target = battle.ships[target_id]
    spec: WeaponSpec = WEAPONS[weapon]

    rng_dist = hex_distance(attacker.pos, target.pos)
    to_hit = spec.to_hit_at(rng_dist)
    roll = int(rng.randint(1, 10))
    hit = (to_hit is not None) and (roll >= to_hit)

    raw_damage = spec.damage_at(rng_dist)

    event = FireEvent(
        attacker_id=attacker_id,
        target_id=target_id,
        weapon=weapon,
        range=rng_dist,
        roll=roll,
        to_hit=to_hit,
        hit=hit,
        raw_damage=raw_damage,
    )

    if not hit or raw_damage <= 0:
        return battle, event

    if target.systems is None:
        # No systems model => nothing to damage yet
        return battle, event

    new_systems = target.systems.apply_weapon_damage(raw_damage, weapon=spec)
    new_target = type(target)(
        ship_id=target.ship_id,
        owner_id=target.owner_id,
        pos=target.pos,
        facing=target.facing,
        mp=target.mp,
        turn_cost=target.turn_cost,
        turn_charge=target.turn_charge,
        systems=new_systems,
    )
    return battle.with_ship(new_target), event

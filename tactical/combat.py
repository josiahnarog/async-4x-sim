from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from sim.hexgrid import Hex
from tactical.battle_state import BattleState, ShipID
from tactical.weapons import WEAPONS, WeaponType, WeaponSpec
from tactical.missile_volley import resolve_missile_volley


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
    # missile-specific fields (None for non-missile weapons)
    missile_hits: Optional[int] = None
    pd_intercepted: Optional[int] = None
    remaining_hits: Optional[int] = None


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
    # Missile weapon: roll-to-hit -> hits -> PD engages hits -> remaining hits apply as damage points.
    if weapon == WeaponType.STANDARD_MISSILE:
        to_hit = spec.to_hit_at(rng_dist)
        hits = 0
        last_roll = 0

        if to_hit is not None:
            for _ in range(spec.rate_of_fire):
                last_roll = int(rng.randint(1, 10))
                if last_roll >= to_hit:
                    hits += 1

        intercepted = 0
        remaining = hits

        if hits > 0 and target.systems is not None:
            pd_shots, pd_to_hit = target.systems.point_defense()
            if pd_shots > 0 and pd_to_hit > 0:
                res = resolve_missile_volley(
                    incoming_hits=hits,
                    pd_shots=pd_shots,
                    pd_to_hit=pd_to_hit,
                    rng=rng,
                )
                intercepted = res.intercepted
                remaining = res.remaining_hits

        event = FireEvent(
            attacker_id=attacker_id,
            target_id=target_id,
            weapon=weapon,
            range=rng_dist,
            roll=last_roll,
            to_hit=to_hit,
            hit=(hits > 0),
            raw_damage=remaining,
            missile_hits=hits,
            pd_intercepted=intercepted,
            remaining_hits=remaining,
        )

        if remaining <= 0 or target.systems is None:
            return battle, event

        new_systems = target.systems.apply_weapon_damage(remaining, weapon=spec)

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

    # Beam weapons (existing behavior)
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

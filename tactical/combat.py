from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from sim.hexgrid import Hex
from tactical.battle_state import BattleState, ShipID
from tactical.weapons import WEAPONS, WeaponType, WeaponSpec
from tactical.missile_volley import resolve_missile_volley
from tactical.attack_context import AttackContext, TargetClass, ToHitMod
from tactical.to_hit import combine_mods, resolve_to_hit, check_hit, roll_hits_target


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

    base_range = hex_distance(attacker.pos, target.pos)

    # Placeholder hook: later we can add ECM/evasion/missile countermeasures here.
    mods = combine_mods([])  # no modifiers yet

    effective_range = max(0, base_range + mods.range_shift)
    ctx = AttackContext(
        target_class=TargetClass.SHIP,
        base_range=base_range,
        effective_range=effective_range,
    )

    # -------------------------
    # Missile weapons
    # -------------------------
    if weapon == WeaponType.STANDARD_MISSILE:
        base_to_hit = spec.to_hit_at(effective_range)
        # Resolve final to-hit target number (may be None if '-' cutoff)
        res = resolve_to_hit(base_to_hit=base_to_hit, ctx=ctx, mods=mods)
        to_hit = res.target

        hits = 0
        last_roll = 0

        if to_hit is not None:
            # MVP: each intact 'R' launcher contributes one missile per firing
            launcher_count = attacker.systems.active_count("R") if attacker.systems is not None else 0
            shots = launcher_count * spec.rate_of_fire

            for _ in range(shots):
                last_roll = int(rng.randint(1, 10))
                check = roll_hits_target(
                    roll=last_roll,
                    base_target=to_hit,
                    target_delta=0,
                    roll_delta=res.roll_delta,
                )
                if check.hit:
                    hits += 1

        intercepted = 0
        remaining = hits

        if hits > 0 and target.systems is not None:
            pd_shots, pd_to_hit = target.systems.point_defense()
            if pd_shots > 0 and pd_to_hit > 0:
                volley = resolve_missile_volley(
                    incoming_hits=hits,
                    pd_shots=pd_shots,
                    pd_to_hit=pd_to_hit,
                    rng=rng,
                )
                intercepted = volley.intercepted
                remaining = volley.remaining_hits

        event = FireEvent(
            attacker_id=attacker_id,
            target_id=target_id,
            weapon=weapon,
            range=base_range,
            roll=last_roll,
            to_hit=to_hit,
            hit=(hits > 0),
            raw_damage=remaining,  # remaining hits apply as damage points for now
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

    # -------------------------
    # Beam weapons (existing behavior, but canonical hit logic)
    # -------------------------
    roll = int(rng.randint(1, 10))

    base_to_hit = spec.to_hit_at(effective_range)
    res = resolve_to_hit(base_to_hit=base_to_hit, ctx=ctx, mods=mods)
    to_hit = res.target

    check = roll_hits_target(
        roll=roll,
        base_target=to_hit,
        target_delta=0,
        roll_delta=res.roll_delta,
    )
    hit = check.hit

    raw_damage = spec.damage_at(base_range)

    event = FireEvent(
        attacker_id=attacker_id,
        target_id=target_id,
        weapon=weapon,
        range=base_range,
        roll=roll,
        to_hit=to_hit,
        hit=hit,
        raw_damage=raw_damage,
    )

    if not hit or raw_damage <= 0:
        return battle, event

    if target.systems is None:
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


from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from sim.hexgrid import Hex, hex_distance
from tactical.battle_state import BattleState, ShipID
from tactical.weapons import WEAPONS, WeaponType, WeaponSpec, WeaponArc
from tactical.missile_volley import resolve_missile_volley
from tactical.attack_context import AttackContext, TargetClass, ToHitMod
from tactical.to_hit import combine_mods, resolve_to_hit, roll_hits_target
from tactical.arcs import arc_of, relative_bearing, Arc, REAR_BEARINGS, REAR_ARC_TO_HIT_BONUS, assert_can_fire


class RNG(Protocol):
    def randint(self, a: int, b: int) -> int: ...


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
    missile_rolls: Optional[tuple[int, ...]] = None  # per-missile roll results
    pd_rolls: Optional[tuple[int, ...]] = None       # per-PD-shot roll results
    ammo_consumed: int = 0                           # rounds expended by this firing
    # Needle beam fields (None for non-needle weapons)
    needle_penetration_roll: Optional[int] = None   # d10 roll for penetration depth
    needle_target_idx: Optional[int] = None         # index in target.systems that is hit


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

    dq = target.pos.q - attacker.pos.q
    dr = target.pos.r - attacker.pos.r
    rb_from_attacker = assert_can_fire(int(attacker.facing), attacker.pos, target.pos, attacker_id, target_id)

    # Per-weapon arc restriction (e.g. FORWARD-only weapons).
    if spec.firing_arc == WeaponArc.FORWARD and rb_from_attacker != 0:
        raise ValueError(
            f"{weapon.value} weapon on {attacker_id} has FORWARD-only arc; "
            f"target is at relative bearing {rb_from_attacker}"
        )

    # Arc modifiers: bonus to-hit when attacking from the target's blind spot.
    attacker_in_target_rear = arc_of(int(target.facing), -dq, -dr) == Arc.REAR
    arc_target_delta = REAR_ARC_TO_HIT_BONUS if attacker_in_target_rear else 0
    condition_mod = attacker.systems.shooting_mods() if attacker.systems is not None else ToHitMod()
    mods = combine_mods([ToHitMod(target_delta=arc_target_delta), condition_mod])

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
        all_rolls: list[int] = []
        missiles_fired = 0

        if to_hit is not None:
            # Each intact 'R' launcher contributes one missile, capped by available ammo.
            launcher_count = attacker.systems.active_count("R") if attacker.systems is not None else 0
            available_ammo = attacker.systems.ammo_count_for("R") if attacker.systems is not None else 0
            effective_launchers = min(launcher_count, available_ammo)
            shots = effective_launchers * spec.rate_of_fire
            missiles_fired = shots

            for _ in range(shots):
                last_roll = int(rng.randint(1, 10))
                all_rolls.append(last_roll)
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
        pd_rolls_out: Optional[tuple[int, ...]] = None

        if hits > 0 and target.systems is not None and not attacker_in_target_rear:
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
                pd_rolls_out = volley.pd_rolls

        event = FireEvent(
            attacker_id=attacker_id,
            target_id=target_id,
            weapon=weapon,
            range=base_range,
            roll=last_roll,
            to_hit=to_hit,
            hit=(hits > 0),
            raw_damage=remaining,
            missile_hits=hits,
            pd_intercepted=intercepted,
            remaining_hits=remaining,
            missile_rolls=tuple(all_rolls),
            pd_rolls=pd_rolls_out,
            ammo_consumed=missiles_fired,
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
            hull_type=target.hull_type,
        )
        return battle.with_ship(new_target), event

    # -------------------------
    # Needle beam weapons
    # -------------------------
    if spec.needle_skip > 0:
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

        needle_roll: Optional[int] = None
        needle_idx: Optional[int] = None

        if hit and target.systems is not None:
            needle_roll = int(rng.randint(1, 10))
            needle_idx = target.systems.needle_beam_target(needle_roll, spec.needle_skip)

        raw_damage = 1 if (hit and needle_idx is not None) else 0

        event = FireEvent(
            attacker_id=attacker_id,
            target_id=target_id,
            weapon=weapon,
            range=base_range,
            roll=roll,
            to_hit=to_hit,
            hit=hit,
            raw_damage=raw_damage,
            needle_penetration_roll=needle_roll,
            needle_target_idx=needle_idx,
        )

        if needle_idx is not None:
            new_systems = target.systems.destroy_system_at(needle_idx)
            new_target = type(target)(
                ship_id=target.ship_id,
                owner_id=target.owner_id,
                pos=target.pos,
                facing=target.facing,
                mp=target.mp,
                turn_cost=target.turn_cost,
                turn_charge=target.turn_charge,
                systems=new_systems,
                hull_type=target.hull_type,
            )
            return battle.with_ship(new_target), event

        return battle, event

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
        hull_type=target.hull_type,
    )
    return battle.with_ship(new_target), event


# Weapon system codes that map to WeaponType values
_WEAPON_CODES: dict[str, WeaponType] = {wt.value: wt for wt in WeaponType}


def resolve_fire_all(
    battle: BattleState,
    *,
    attacker_id: ShipID,
    target_id: ShipID,
    rng: RNG,
) -> tuple[BattleState, list[FireEvent]]:
    """Fire all active weapons on attacker at target.

    Beams (L, E, F): one firing per active weapon instance.
    Missiles (R): all active launchers fire as a single volley (handled by resolve_large_fire).
    """
    attacker = battle.ships[attacker_id]
    target = battle.ships[target_id]

    if attacker.systems is None:
        return battle, []

    rb = assert_can_fire(int(attacker.facing), attacker.pos, target.pos, attacker_id, target_id)

    events: list[FireEvent] = []
    missile_fired = False

    for system in attacker.systems:
        if not system.is_active():
            continue
        weapon_type = _WEAPON_CODES.get(system.base)
        if weapon_type is None:
            continue

        # Per-weapon arc restriction (e.g. FORWARD-only weapons).
        spec = WEAPONS[weapon_type]
        if spec.firing_arc == WeaponArc.FORWARD and rb != 0:
            continue  # this weapon cannot reach that bearing

        if weapon_type == WeaponType.STANDARD_MISSILE:
            if missile_fired:
                continue  # all launchers already resolved as one volley
            missile_fired = True

        battle, ev = resolve_large_fire(
            battle,
            attacker_id=attacker_id,
            target_id=target_id,
            weapon=weapon_type,
            rng=rng,
        )
        events.append(ev)

    return battle, events


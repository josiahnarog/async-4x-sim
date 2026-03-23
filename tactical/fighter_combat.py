"""Fighter combat resolution for the COMBAT_SMALL phase.

Resolution sequence:
  1.  Movement       — squadrons move to their ordered destinations.
  1b. Break-offs     — parting shots from co-hex enemies; breaker then moves.
  1c. Intercept      — interceptors close on enemies within radius.
  2.  Dogfights      — simultaneously resolved from post-movement snapshot.
  3.  Attack runs    — strike squadrons hit capital ships (post-dogfight state).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Protocol

import dataclasses

from sim.hexgrid import Hex, hex_distance
from tactical.battle_state import BattleState, ShipID
from tactical.events import DestructionCause, UnitDestroyedEvent
from tactical.fighter_events import (
    AttackRunEvent,
    BreakOffEvent,
    DogfightEvent,
    FighterCombatEvent,
    FighterShotEvent,
)
from tactical.squadron_state import SquadronID, SquadronState
from tactical.to_hit import clamp_int
from tactical.weapons import WEAPONS


class RNG(Protocol):
    def randint(self, a: int, b: int) -> int: ...


# ---------------------------------------------------------------------------
# Hex movement utility
# ---------------------------------------------------------------------------

# Axial neighbours in the six flat-top directions
_NEIGHBOURS = [
    Hex( 0,  1), Hex( 1,  0), Hex( 1, -1),
    Hex( 0, -1), Hex(-1,  0), Hex(-1,  1),
]


def _step_toward(origin: Hex, dest: Hex, mp: int) -> Hex:
    """Move up to `mp` steps from origin toward dest along the shortest path.

    Each step moves to whichever neighbour minimises the remaining distance to
    dest.  Returns the hex reached after consuming up to `mp` steps (or dest
    itself if reachable within mp).
    """
    pos = origin
    for _ in range(mp):
        if pos == dest:
            break
        best = min(
            _NEIGHBOURS,
            key=lambda dh: hex_distance(Hex(pos.q + dh.q, pos.r + dh.r), dest),
        )
        pos = Hex(pos.q + best.q, pos.r + best.r)
    return pos


# ---------------------------------------------------------------------------
# Dogfight resolution
# ---------------------------------------------------------------------------

def _pick_dogfight_target(
    attacker: SquadronState,
    enemies: list[SquadronState],
) -> SquadronState:
    """Weakest enemy (lowest strength); ties broken by squadron_id for determinism."""
    return min(enemies, key=lambda sq: (sq.strength, sq.squadron_id))


def _squadron_fires_at_squadron(
    attacker: SquadronState,
    target: SquadronState,
    *,
    rng: RNG,
) -> tuple[int, tuple[FighterShotEvent, ...]]:
    """Fire all internal weapons of attacker's surviving fighters at target.

    Only internal weapons are usable in dogfights (missiles cannot target
    fighters and are automatically skipped).

    MVR modifier: (attacker.effective_mvr - target.effective_mvr) added to
    every weapon's to-hit target.  Each weapon's anti_fighter_modifier also
    applies.  Each hit kills exactly one fighter regardless of weapon damage.

    Returns (total_casualties, shots_tuple).
    """
    mvr_delta        = attacker.effective_mvr - target.effective_mvr
    total_casualties = 0
    shots: list[FighterShotEvent] = []

    for _ in range(attacker.strength):
        for weapon_type in attacker.loadout.internal:
            spec = WEAPONS[weapon_type]
            if not spec.can_target_fighters:
                continue
            base_to_hit = spec.to_hit_at(0)
            if base_to_hit is None:
                continue

            final_to_hit = clamp_int(
                base_to_hit + mvr_delta + spec.anti_fighter_modifier,
                0, 10,
            )
            roll = int(rng.randint(1, 10))
            hit  = roll <= final_to_hit
            dmg  = 1 if hit else 0
            total_casualties += dmg
            shots.append(FighterShotEvent(
                weapon=weapon_type, roll=roll, to_hit=final_to_hit,
                hit=hit, damage=dmg,
            ))

    return total_casualties, tuple(shots)


def resolve_all_dogfights(
    snapshot: BattleState,
    *,
    rng: RNG,
) -> tuple[BattleState, list[DogfightEvent]]:
    """Resolve all ongoing dogfights simultaneously.

    A dogfight occurs in any hex that contains squadrons from two or more
    sides.  All fire is resolved against `snapshot`; casualties are accumulated
    per target and applied in a single pass at the end so that neither side
    has an advantage from turn order.  Destroyed squadrons are removed.
    """
    hex_squads: dict[Hex, list[SquadronState]] = defaultdict(list)
    for sq in snapshot.squadrons.values():
        if sq.is_deployed:
            hex_squads[sq.pos].append(sq)

    events: list[DogfightEvent] = []
    casualties_per_target: dict[SquadronID, int] = {}

    for squads in hex_squads.values():
        owners = {sq.owner_id for sq in squads}
        if len(owners) < 2:
            continue
        for attacker in squads:
            enemies = [sq for sq in squads if sq.owner_id != attacker.owner_id]
            if not enemies:
                continue
            target = _pick_dogfight_target(attacker, enemies)
            total_cas, shots = _squadron_fires_at_squadron(attacker, target, rng=rng)
            events.append(DogfightEvent(
                attacker_id=attacker.squadron_id,
                target_id=target.squadron_id,
                mvr_delta=attacker.effective_mvr - target.effective_mvr,
                shots=shots,
                total_casualties=total_cas,
            ))
            casualties_per_target[target.squadron_id] = (
                casualties_per_target.get(target.squadron_id, 0) + total_cas
            )

    new_battle = snapshot
    for sq_id, casualties in casualties_per_target.items():
        if sq_id not in new_battle.squadrons:
            continue
        sq     = new_battle.squadrons[sq_id]
        new_sq = sq.take_casualties(casualties)
        if new_sq.is_destroyed():
            new_battle = new_battle.without_squadron(sq_id)
            events.append(UnitDestroyedEvent(sq_id, DestructionCause.DOGFIGHT))
        else:
            new_battle = new_battle.with_squadron(new_sq)

    return new_battle, events


# ---------------------------------------------------------------------------
# Attack run resolution
# ---------------------------------------------------------------------------

def resolve_attack_run(
    battle: BattleState,
    *,
    attacker_id: SquadronID,
    target_ship_id: ShipID,
    rng: RNG,
    simultaneous: bool = False,
) -> tuple[BattleState, AttackRunEvent]:
    """Resolve a fighter squadron's attack run on a capital ship.

    Phase 1 — PD fires at incoming fighters:
      Point-defense fires at the approaching squadron regardless of arc.
      Each PD hit kills one fighter.

    Phase 2 — Fighters fire weapons:
      Each surviving fighter fires its internal weapons at range 0.
      If external_shots_remaining > 0, external weapons also fire and one
      salvo's worth of ordnance is expended.

    If simultaneous=True (transit attack runs during movement), all fighters
    fire at full pre-PD strength before PD casualties are applied — both sides
    fire at the same time.
    """
    attacker = battle.squadrons[attacker_id]
    target   = battle.ships[target_ship_id]

    # Phase 1: PD
    pd_shots_fired  = 0
    pd_hits         = 0
    pd_rolls: list[int] = []
    fighters_killed = 0

    if target.systems is not None and attacker.strength > 0:
        pd_shots_total, pd_to_hit = target.systems.point_defense()
        if pd_shots_total > 0 and pd_to_hit > 0:
            shots_to_fire  = min(pd_shots_total, attacker.strength)
            pd_shots_fired = shots_to_fire
            for _ in range(shots_to_fire):
                roll = int(rng.randint(1, 10))
                pd_rolls.append(roll)
                if roll <= pd_to_hit:
                    pd_hits += 1
            fighters_killed = min(pd_hits, attacker.strength)

    surviving_strength = max(0, attacker.strength - fighters_killed)
    firing_strength    = attacker.strength if simultaneous else surviving_strength

    if fighters_killed > 0:
        updated = attacker.take_casualties(fighters_killed)
        if updated.is_destroyed():
            battle = battle.without_squadron(attacker_id)
        else:
            battle = battle.with_squadron(updated)

    # Phase 2: Weapon fire
    weapon_shots: list[FighterShotEvent] = []
    damage_queue: list[tuple[int, object]] = []
    fire_external = (
        firing_strength > 0
        and attacker.loadout.external_shots_remaining > 0
    )

    for _ in range(firing_strength):
        for weapon_type in attacker.loadout.internal:
            spec        = WEAPONS[weapon_type]
            base_to_hit = spec.to_hit_at(0)
            if base_to_hit is None:
                continue
            roll = int(rng.randint(1, 10))
            hit  = roll <= base_to_hit
            dmg  = spec.damage_at(0) if hit else 0
            if hit and dmg > 0:
                damage_queue.append((dmg, spec))
            weapon_shots.append(FighterShotEvent(
                weapon=weapon_type, roll=roll, to_hit=base_to_hit,
                hit=hit, damage=dmg,
            ))

        if fire_external:
            for weapon_type in attacker.loadout.external:
                spec        = WEAPONS[weapon_type]
                base_to_hit = spec.to_hit_at(0)
                if base_to_hit is None:
                    continue
                roll = int(rng.randint(1, 10))
                hit  = roll <= base_to_hit
                dmg  = spec.damage_at(0) if hit else 0
                if hit and dmg > 0:
                    damage_queue.append((dmg, spec))
                weapon_shots.append(FighterShotEvent(
                    weapon=weapon_type, roll=roll, to_hit=base_to_hit,
                    hit=hit, damage=dmg,
                ))

    total_damage = sum(d for d, _ in damage_queue)
    if damage_queue and target.systems is not None:
        new_systems = target.systems
        for dmg, spec in damage_queue:
            new_systems = new_systems.apply_weapon_damage(dmg, weapon=spec)
        battle = battle.with_ship(dataclasses.replace(target, systems=new_systems))

    if fire_external and attacker_id in battle.squadrons:
        battle = battle.with_squadron(battle.squadrons[attacker_id].expend_external_shot())

    return battle, AttackRunEvent(
        attacker_id=attacker_id,
        target_id=target_ship_id,
        pd_shots_fired=pd_shots_fired,
        pd_hits=pd_hits,
        pd_rolls=tuple(pd_rolls),
        fighters_killed_by_pd=fighters_killed,
        surviving_strength=surviving_strength,
        weapon_shots=tuple(weapon_shots),
        total_ship_damage=total_damage,
    )


# ---------------------------------------------------------------------------
# resolve_combat_small sub-steps
# ---------------------------------------------------------------------------

def _move_squadrons(
    battle: BattleState,
    squadron_orders: dict[SquadronID, object],
) -> tuple[BattleState, dict[SquadronID, ShipID], dict[SquadronID, object]]:
    """Apply movement for all non-break-off orders.

    Returns (new_battle, strike_ship_targets, break_off_orders) where
    strike_ship_targets maps each squadron that reached an enemy ship's hex to
    that ship's ID, and break_off_orders collects orders to be resolved later.
    """
    from tactical.turn_orders import BreakOffOrder, InterceptOrder, MoveOrder, StrikeOrder

    strike_ship_targets: dict[SquadronID, ShipID] = {}
    break_off_orders: dict[SquadronID, object]    = {}

    for sq_id, order in squadron_orders.items():
        if sq_id not in battle.squadrons:
            continue
        sq = battle.squadrons[sq_id]
        if not sq.is_deployed:
            continue

        if isinstance(order, BreakOffOrder):
            break_off_orders[sq_id] = order

        elif isinstance(order, MoveOrder):
            new_pos = _step_toward(sq.pos, order.dest, sq.effective_mp)
            battle  = battle.with_squadron(sq.move_to(new_pos))

        elif isinstance(order, InterceptOrder):
            new_pos = _step_toward(sq.pos, order.patrol_hex, sq.effective_mp)
            battle  = battle.with_squadron(sq.move_to(new_pos))

        elif isinstance(order, StrikeOrder):
            target_id = order.target_id
            if target_id in battle.ships:
                ship_pos = battle.ships[target_id].pos
                new_pos  = _step_toward(sq.pos, ship_pos, sq.effective_mp)
                battle   = battle.with_squadron(sq.move_to(new_pos))
                if new_pos == ship_pos:
                    strike_ship_targets[sq_id] = target_id
            elif target_id in battle.squadrons:
                enemy_pos = battle.squadrons[target_id].pos
                new_pos   = _step_toward(sq.pos, enemy_pos, sq.effective_mp)
                battle    = battle.with_squadron(sq.move_to(new_pos))

    return battle, strike_ship_targets, break_off_orders


def _resolve_break_offs(
    battle: BattleState,
    break_off_orders: dict[SquadronID, object],
    rng: RNG,
) -> tuple[BattleState, list]:
    """Resolve break-off orders: parting shots then movement.

    Each enemy squadron co-located with the breaking squadron fires parting
    shots before the breaker moves.  The breaker moves as far as its MP allows
    toward its requested destination even if it took casualties.
    """
    from tactical.turn_orders import BreakOffOrder

    events: list = []
    for sq_id, order in break_off_orders.items():
        if sq_id not in battle.squadrons:
            continue
        if not isinstance(order, BreakOffOrder):
            continue
        sq = battle.squadrons[sq_id]

        parting: list[DogfightEvent] = []
        total_parting_cas = 0
        co_hex_enemies = [
            esq for esq in battle.squadrons.values()
            if esq.owner_id != sq.owner_id and esq.pos == sq.pos
        ]
        for enemy in co_hex_enemies:
            cas, shots = _squadron_fires_at_squadron(enemy, sq, rng=rng)
            parting.append(DogfightEvent(
                attacker_id=enemy.squadron_id,
                target_id=sq_id,
                mvr_delta=enemy.effective_mvr - sq.effective_mvr,
                shots=shots,
                total_casualties=cas,
            ))
            total_parting_cas += cas

        if total_parting_cas > 0 and sq_id in battle.squadrons:
            updated = battle.squadrons[sq_id].take_casualties(total_parting_cas)
            if updated.is_destroyed():
                battle = battle.without_squadron(sq_id)
                events.append(UnitDestroyedEvent(sq_id, DestructionCause.DOGFIGHT))
            else:
                battle = battle.with_squadron(updated)

        if sq_id in battle.squadrons:
            sq_now  = battle.squadrons[sq_id]
            new_pos = _step_toward(sq_now.pos, order.dest, sq_now.effective_mp)
            battle  = battle.with_squadron(sq_now.move_to(new_pos))
        else:
            new_pos = sq.pos

        events.append(BreakOffEvent(
            squadron_id=sq_id,
            dest=order.dest,
            parting_shots=tuple(parting),
            casualties_taken=total_parting_cas,
            final_pos=new_pos,
        ))

    return battle, events


def _engage_interceptors(
    battle: BattleState,
    squadron_orders: dict[SquadronID, object],
    original_positions: dict[SquadronID, Hex],
) -> BattleState:
    """Close interceptors on the nearest enemy within their intercept radius.

    Intercept radius = (effective_mp - dist_to_patrol) + 1, capped by
    max_intercept_radius if the order specifies one.  The interceptor moves
    directly to the enemy's hex so that the dogfight detector picks them up in
    the next step.
    """
    from tactical.turn_orders import InterceptOrder

    for sq_id, order in squadron_orders.items():
        if sq_id not in battle.squadrons:
            continue
        if not isinstance(order, InterceptOrder):
            continue
        sq = battle.squadrons[sq_id]
        if not sq.is_deployed:
            continue

        orig_pos       = original_positions.get(sq_id, sq.pos)
        dist_to_patrol = hex_distance(orig_pos, order.patrol_hex)
        remaining_mp   = max(0, sq.effective_mp - dist_to_patrol)
        radius         = remaining_mp + 1
        if order.max_intercept_radius is not None:
            radius = min(radius, order.max_intercept_radius)

        enemies_in_range = [
            (hex_distance(sq.pos, esq.pos), eid)
            for eid, esq in battle.squadrons.items()
            if esq.owner_id != sq.owner_id
            and esq.is_deployed
            and hex_distance(sq.pos, esq.pos) <= radius
        ]
        if enemies_in_range:
            _, target_id = min(enemies_in_range)
            battle = battle.with_squadron(sq.move_to(battle.squadrons[target_id].pos))

    return battle


def _resolve_attack_runs(
    battle: BattleState,
    strike_ship_targets: dict[SquadronID, ShipID],
    rng: RNG,
) -> tuple[BattleState, list]:
    """Resolve simultaneous attack runs for all strike squadrons that reached a ship.

    Only unengaged squadrons make attack runs — a squadron sharing its hex with
    an enemy after dogfights is locked in and cannot break away for a run.
    """
    engaged_ids = {sq.squadron_id for sq, _ in battle.engaged_squadrons()}
    events: list = []

    for sq_id, ship_id in strike_ship_targets.items():
        if sq_id in engaged_ids:
            continue
        if sq_id not in battle.squadrons:
            continue
        if ship_id not in battle.ships:
            continue

        battle, ar_event = resolve_attack_run(
            battle, attacker_id=sq_id, target_ship_id=ship_id, rng=rng,
        )
        events.append(ar_event)

        if sq_id not in battle.squadrons:
            events.append(UnitDestroyedEvent(sq_id, DestructionCause.POINT_DEFENSE))

        if ship_id in battle.ships:
            ship = battle.ships[ship_id]
            if ship.systems is not None and ship.systems.is_destroyed():
                events.append(UnitDestroyedEvent(ship_id, DestructionCause.ENEMY_FIRE))

    return battle, events


# ---------------------------------------------------------------------------
# Top-level COMBAT_SMALL resolver
# ---------------------------------------------------------------------------

def resolve_combat_small(
    battle: BattleState,
    squadron_orders: dict[SquadronID, object],
    *,
    rng: RNG,
) -> tuple[BattleState, list[FighterCombatEvent]]:
    """Fully resolve the COMBAT_SMALL phase.

    Step 1  — Movement: each squadron moves toward its ordered destination.
    Step 1b — Break-offs: parting shots from co-hex enemies, then movement.
    Step 1c — Intercept: interceptors close on enemies within their radius.
    Step 2  — Dogfights: simultaneous fire in every contested hex.
    Step 3  — Attack runs: strike squadrons hit capital ships.
    """
    original_positions: dict[SquadronID, Hex] = {
        sq_id: sq.pos
        for sq_id, sq in battle.squadrons.items()
        if sq.is_deployed
    }

    # Step 1: Move all squadrons to their ordered destinations.
    battle, strike_ship_targets, break_off_orders = _move_squadrons(battle, squadron_orders)

    # Step 1b: Break-offs — parting shots then movement.
    battle, break_off_events = _resolve_break_offs(battle, break_off_orders, rng)

    # Step 1c: Intercept engagement — interceptors close on enemies in range.
    battle = _engage_interceptors(battle, squadron_orders, original_positions)

    # Step 2: Dogfights — simultaneous from post-movement snapshot.
    battle, dogfight_events = resolve_all_dogfights(battle, rng=rng)

    # Step 3: Attack runs — post-dogfight state; destroyed strike squadrons pruned.
    strike_ship_targets = {
        sq_id: ship_id
        for sq_id, ship_id in strike_ship_targets.items()
        if sq_id in battle.squadrons
    }
    battle, attack_run_events = _resolve_attack_runs(battle, strike_ship_targets, rng)

    return battle, break_off_events + dogfight_events + attack_run_events

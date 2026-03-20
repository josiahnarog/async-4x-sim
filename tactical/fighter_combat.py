"""Fighter combat resolution for the COMBAT_SMALL phase.

Resolution sequence within COMBAT_SMALL:
  1. Squadrons move according to their orders:
       INTERCEPT  → patrol hex (partial movement if unreachable)
       STRIKE     → toward target (partial movement if unreachable)
       BREAK_OFF  → parting shots fired by each co-hex enemy, then move to dest
  1b. Intercept engagement: interceptors check enemies within radius and close.
  2. Dogfights resolve simultaneously (snapshot fire, one-pass casualties).
  3. Attack runs resolve simultaneously (post-dogfight state).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Optional, Protocol, Union

from sim.hexgrid import Hex
from tactical.battle_state import BattleState, ShipID
from tactical.events import DestructionCause, UnitDestroyedEvent
from tactical.squadron_state import SquadronID, SquadronState
from tactical.to_hit import roll_hits_target, clamp_int
from tactical.weapons import WEAPONS, WeaponType


class RNG(Protocol):
    def randint(self, a: int, b: int) -> int: ...


# ---------------------------------------------------------------------------
# Movement utility
# ---------------------------------------------------------------------------

# Axial neighbours in the six flat-top directions
_NEIGHBOURS = [
    Hex( 0,  1), Hex( 1,  0), Hex( 1, -1),
    Hex( 0, -1), Hex(-1,  0), Hex(-1,  1),
]


def _step_toward(origin: Hex, dest: Hex, mp: int) -> Hex:
    """Move up to `mp` steps from origin toward dest along the shortest path.

    Each step moves to whichever neighbour minimises remaining distance to dest.
    Returns the hex reached after consuming up to `mp` steps (or dest if reachable).
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


def hex_distance(a: Hex, b: Hex) -> int:
    dq = abs(a.q - b.q)
    dr = abs(a.r - b.r)
    ds = abs((a.q + a.r) - (b.q + b.r))
    return max(dq, dr, ds)


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FighterShotEvent:
    """One fighter's single weapon shot in a dogfight or attack run."""
    weapon:  WeaponType
    roll:    int
    to_hit:  int    # final adjusted target number
    hit:     bool
    damage:  int    # casualties vs squadron; system-hit damage vs ship


@dataclass(frozen=True, slots=True)
class DogfightEvent:
    """One squadron fires all its internal weapons at a target squadron."""
    attacker_id:       SquadronID
    target_id:         SquadronID
    mvr_delta:         int                      # attacker_mvr - target_mvr
    shots:             tuple[FighterShotEvent, ...]
    total_casualties:  int


@dataclass(frozen=True, slots=True)
class AttackRunEvent:
    """A fighter squadron makes an attack run on a capital ship."""
    attacker_id:          SquadronID
    target_id:            ShipID
    # PD phase — PD fires at the incoming fighters before they can shoot
    pd_shots_fired:       int
    pd_hits:              int
    pd_rolls:             tuple[int, ...]
    fighters_killed_by_pd: int
    surviving_strength:   int
    # Weapon phase — surviving fighters fire at range 0
    weapon_shots:         tuple[FighterShotEvent, ...]
    total_ship_damage:    int


@dataclass(frozen=True, slots=True)
class BreakOffEvent:
    """A squadron broke off from a dogfight.

    Parting shots are taken by each enemy squadron that shared the hex.
    The breaking squadron then moves to its destination (or as far as MP allows).
    """
    squadron_id:        SquadronID
    dest:               "Hex"           # noqa: F821
    parting_shots:      tuple[DogfightEvent, ...]   # one per attacking enemy squad
    casualties_taken:   int
    final_pos:          "Hex"           # noqa: F821


FighterCombatEvent = Union[DogfightEvent, AttackRunEvent, BreakOffEvent, UnitDestroyedEvent]


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

    Only internal weapons are usable in dogfights; R (can_target_fighters=False)
    is automatically skipped.

    MVR modifier: (attacker.effective_mvr - target.effective_mvr) applied to
    every weapon's to-hit target.  Weapon anti_fighter_modifier also applied.

    Returns (total_casualties, shots_tuple).
    """
    mvr_delta = attacker.effective_mvr - target.effective_mvr
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
            hit = roll <= final_to_hit
            dmg = 1 if hit else 0   # each hit kills one fighter regardless of weapon damage
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

    A dogfight occurs in any hex that contains squadrons from 2+ sides.
    Simultaneity: all fire against snapshot; casualties accumulated per
    target and applied in one pass at the end.
    Destroyed squadrons (strength reaches 0) are removed from the battle.
    """
    from collections import defaultdict

    # Group squadrons by hex (docked squadrons are excluded)
    hex_squads: dict[Hex, list[SquadronState]] = defaultdict(list)
    for sq in snapshot.squadrons.values():
        if not sq.is_deployed:
            continue
        hex_squads[sq.pos].append(sq)

    events: list[DogfightEvent] = []
    casualties_queue: dict[SquadronID, int] = {}

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
            casualties_queue[target.squadron_id] = (
                casualties_queue.get(target.squadron_id, 0) + total_cas
            )

    # Apply accumulated casualties
    new_battle = snapshot
    for sq_id, casualties in casualties_queue.items():
        if sq_id not in new_battle.squadrons:
            continue
        sq = new_battle.squadrons[sq_id]
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

    Phase 1 — PD fires at the incoming fighters:
      The target ship's point-defense fires at the approaching squadron.
      Each PD hit kills one fighter (reduces attacker strength by 1).
      PD fires regardless of the ship's facing (fighters swoop from all angles).

    Phase 2 — Fighters fire weapons:
      Internal weapons: each fighter fires each internal weapon once at
        range 0.  No arc checks — the fighter has maneuvered to firing
        position.
      External weapons: if external_shots_remaining > 0, each fighter
        also fires each external weapon once at range 0.  One external
        shot is expended after the salvo.
      Weapon damage accumulated and applied to target ship systems.

    If simultaneous=True (transit attack runs), all fighters at full
    strength fire their weapons regardless of PD casualties — both the
    fighters and the PD fire at the same time.  PD casualties are still
    applied to the squadron after the exchange.
    """
    attacker = battle.squadrons[attacker_id]
    target   = battle.ships[target_ship_id]

    # ------------------------------------------------------------------ #
    # Phase 1: PD fires at incoming fighters                              #
    # ------------------------------------------------------------------ #
    pd_shots_fired    = 0
    pd_hits           = 0
    pd_rolls: list[int] = []
    fighters_killed   = 0

    if target.systems is not None and attacker.strength > 0:
        pd_shots_total, pd_to_hit = target.systems.point_defense()
        if pd_shots_total > 0 and pd_to_hit > 0:
            shots_to_fire = min(pd_shots_total, attacker.strength)
            pd_shots_fired = shots_to_fire
            for _ in range(shots_to_fire):
                roll = int(rng.randint(1, 10))
                pd_rolls.append(roll)
                if roll <= pd_to_hit:
                    pd_hits += 1
            fighters_killed = min(pd_hits, attacker.strength)

    surviving_strength = max(0, attacker.strength - fighters_killed)

    # In simultaneous mode (transit), all fighters fire before PD casualties
    # are applied — determine how many fighters fire their weapons.
    firing_strength = attacker.strength if simultaneous else surviving_strength

    # Apply PD casualties to battle state
    if fighters_killed > 0:
        updated = attacker.take_casualties(fighters_killed)
        if updated.is_destroyed():
            battle = battle.without_squadron(attacker_id)
        else:
            battle = battle.with_squadron(updated)

    # ------------------------------------------------------------------ #
    # Phase 2: Fighters fire weapons                                      #
    # ------------------------------------------------------------------ #
    weapon_shots: list[FighterShotEvent] = []
    damage_queue: list[tuple[int, object]] = []   # (damage, WeaponSpec)
    fire_external = (
        firing_strength > 0
        and attacker.loadout.external_shots_remaining > 0
    )

    for _ in range(firing_strength):
        for weapon_type in attacker.loadout.internal:
            spec = WEAPONS[weapon_type]
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
                spec = WEAPONS[weapon_type]
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

    # Apply weapon damage to ship
    total_damage = sum(d for d, _ in damage_queue)
    if damage_queue and target.systems is not None:
        new_systems = target.systems
        for dmg, spec in damage_queue:
            new_systems = new_systems.apply_weapon_damage(dmg, weapon=spec)
        battle = battle.with_ship(dataclasses.replace(target, systems=new_systems))

    # Expend one external shot (one salvo fired by the whole squadron)
    if fire_external and attacker_id in battle.squadrons:
        sq_now = battle.squadrons[attacker_id]
        battle = battle.with_squadron(sq_now.expend_external_shot())

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
# Top-level COMBAT_SMALL resolver
# ---------------------------------------------------------------------------

def resolve_combat_small(
    battle: BattleState,
    squadron_orders: dict[SquadronID, object],  # InterceptOrder | StrikeOrder
    *,
    rng: RNG,
) -> tuple[BattleState, list[FighterCombatEvent]]:
    """Fully resolve the COMBAT_SMALL phase.

    Step 1 — Movement:
      INTERCEPT orders: squad moves to patrol_hex (if reachable within effective_mp).
      STRIKE orders: squad moves toward target; engages if reachable.

    Step 2 — Dogfights:
      Any hex containing squadrons from 2+ sides triggers a dogfight.
      Resolved simultaneously from snapshot.

    Step 3 — Attack runs:
      STRIKE squadrons that reached an enemy ship make an attack run.
      Resolved simultaneously (against post-dogfight state).
    """
    from tactical.turn_orders import BreakOffOrder, InterceptOrder, StrikeOrder

    all_events: list[FighterCombatEvent] = []

    # ------------------------------------------------------------------ #
    # Step 1: Move squadrons                                              #
    # ------------------------------------------------------------------ #
    # Record original positions before any movement for intercept radius
    # calculation (radius = remaining_mp_after_reaching_patrol + 1).
    original_positions: dict[SquadronID, Hex] = {
        sq_id: sq.pos for sq_id, sq in battle.squadrons.items()
        if sq.is_deployed
    }

    # Track which squadrons are striking a ship (for attack-run step)
    strike_ship_targets: dict[SquadronID, ShipID] = {}

    # Break-off orders are handled separately after all other movement
    break_off_orders: dict[SquadronID, BreakOffOrder] = {}

    for sq_id, order in squadron_orders.items():
        if sq_id not in battle.squadrons:
            continue
        sq = battle.squadrons[sq_id]
        if not sq.is_deployed:
            continue  # docked squadrons cannot receive movement orders

        if isinstance(order, BreakOffOrder):
            break_off_orders[sq_id] = order

        elif isinstance(order, InterceptOrder):
            # Move as far as MP allows toward patrol hex (partial movement)
            new_pos = _step_toward(sq.pos, order.patrol_hex, sq.effective_mp)
            battle = battle.with_squadron(sq.move_to(new_pos))

        elif isinstance(order, StrikeOrder):
            target_id = order.target_id

            if target_id in battle.ships:
                # Strike a capital ship — partial movement toward it
                ship_pos = battle.ships[target_id].pos
                new_pos  = _step_toward(sq.pos, ship_pos, sq.effective_mp)
                battle   = battle.with_squadron(sq.move_to(new_pos))
                if new_pos == ship_pos:
                    strike_ship_targets[sq_id] = target_id

            elif target_id in battle.squadrons:
                # Strike an enemy squadron — partial movement toward it
                enemy_pos = battle.squadrons[target_id].pos
                new_pos   = _step_toward(sq.pos, enemy_pos, sq.effective_mp)
                battle    = battle.with_squadron(sq.move_to(new_pos))
                # Dogfight detected positionally in Step 2

    # ------------------------------------------------------------------ #
    # Step 1c: Resolve break-off orders                                   #
    # ------------------------------------------------------------------ #
    # Each enemy squadron in the same hex fires parting shots at the
    # breaking squadron before it moves.  The breaker then moves as far
    # as its MP allows toward its destination.
    for sq_id, order in break_off_orders.items():
        if sq_id not in battle.squadrons:
            continue
        sq = battle.squadrons[sq_id]

        # Parting shots from every co-hex enemy
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

        # Apply parting casualties
        if total_parting_cas > 0 and sq_id in battle.squadrons:
            sq_now = battle.squadrons[sq_id]
            updated = sq_now.take_casualties(total_parting_cas)
            if updated.is_destroyed():
                battle = battle.without_squadron(sq_id)
                all_events.append(UnitDestroyedEvent(sq_id, DestructionCause.DOGFIGHT))
            else:
                battle = battle.with_squadron(updated)

        # Move as far as MP allows toward dest (even if took casualties)
        if sq_id in battle.squadrons:
            sq_now  = battle.squadrons[sq_id]
            new_pos = _step_toward(sq_now.pos, order.dest, sq_now.effective_mp)
            battle  = battle.with_squadron(sq_now.move_to(new_pos))
        else:
            new_pos = sq.pos   # destroyed — no movement

        all_events.append(BreakOffEvent(
            squadron_id=sq_id,
            dest=order.dest,
            parting_shots=tuple(parting),
            casualties_taken=total_parting_cas,
            final_pos=new_pos,
        ))

    # ------------------------------------------------------------------ #
    # Step 1b: Intercept engagement                                       #
    # ------------------------------------------------------------------ #
    # After all squadrons have reached their final positions, each
    # interceptor checks whether any enemy squadron is within its intercept
    # radius (remaining_mp_after_reaching_patrol + 1).  This covers both
    # enemies that moved into range this turn and enemies that were already
    # within range before the interceptor moved.  The interceptor closes to
    # the enemy's hex so that the dogfight detector picks them up in Step 2.
    for sq_id, order in squadron_orders.items():
        if sq_id not in battle.squadrons:
            continue
        if not isinstance(order, InterceptOrder):
            continue
        sq = battle.squadrons[sq_id]
        if not sq.is_deployed:
            continue  # docked squadrons cannot intercept
        orig_pos = original_positions.get(sq_id, sq.pos)
        dist_to_patrol   = hex_distance(orig_pos, order.patrol_hex)
        remaining_mp     = max(0, sq.effective_mp - dist_to_patrol)
        intercept_radius = remaining_mp + 1

        enemies_in_range = [
            (hex_distance(sq.pos, esq.pos), eid)
            for eid, esq in battle.squadrons.items()
            if esq.owner_id != sq.owner_id
            and esq.is_deployed
            and hex_distance(sq.pos, esq.pos) <= intercept_radius
        ]
        if enemies_in_range:
            _, target_id = min(enemies_in_range)   # closest, ties by id
            target_pos = battle.squadrons[target_id].pos
            battle = battle.with_squadron(sq.move_to(target_pos))

    # ------------------------------------------------------------------ #
    # Step 2: Resolve dogfights (simultaneously from snapshot)            #
    # ------------------------------------------------------------------ #
    dogfight_snapshot = battle
    battle, dogfight_events = resolve_all_dogfights(dogfight_snapshot, rng=rng)
    all_events.extend(dogfight_events)

    # Remove strike-ship targets for squadrons that were destroyed in dogfights
    strike_ship_targets = {
        sq_id: ship_id
        for sq_id, ship_id in strike_ship_targets.items()
        if sq_id in battle.squadrons
    }

    # ------------------------------------------------------------------ #
    # Step 3: Resolve attack runs (simultaneously)                        #
    # ------------------------------------------------------------------ #
    # Only unengaged squadrons can make attack runs.
    # An engaged squadron is one that shares its hex with an enemy squadron
    # after the dogfight step.
    engaged_ids = {sq.squadron_id for sq, _ in battle.engaged_squadrons()}

    for sq_id, ship_id in strike_ship_targets.items():
        if sq_id in engaged_ids:
            continue  # locked in dogfight, can't make attack run
        if sq_id not in battle.squadrons:
            continue  # destroyed in dogfight
        if ship_id not in battle.ships:
            continue  # target ship already destroyed

        battle, ar_event = resolve_attack_run(
            battle,
            attacker_id=sq_id,
            target_ship_id=ship_id,
            rng=rng,
        )
        all_events.append(ar_event)

        # Attacker destroyed by PD
        if sq_id not in battle.squadrons:
            all_events.append(UnitDestroyedEvent(sq_id, DestructionCause.POINT_DEFENSE))

        # Target ship destroyed by attack run
        if ship_id in battle.ships:
            ship = battle.ships[ship_id]
            if ship.systems is not None and ship.systems.is_destroyed():
                all_events.append(UnitDestroyedEvent(ship_id, DestructionCause.ENEMY_FIRE))

    return battle, all_events

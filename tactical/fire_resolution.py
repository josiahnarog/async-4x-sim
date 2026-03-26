"""Standalone fire resolution for the tactical encounter.

Called by Encounter._resolve_fire; separated to keep encounter.py concise.
"""
from __future__ import annotations

import dataclasses
from typing import Optional, TYPE_CHECKING

from tactical.battle_state import BattleState, ShipID
from tactical.combat import FireEvent, resolve_fire_all
from tactical.initiative import RNG
from tactical.turn_orders import ShipFireOrder
from tactical.weapons import WEAPONS

if TYPE_CHECKING:
    pass


def resolve_fire(
    battle: BattleState,
    fire_orders: dict[ShipID, Optional[ShipFireOrder]],
    revealed_systems: dict[str, frozenset[int]],
    rng: RNG,
) -> tuple[BattleState, list[FireEvent], dict[str, frozenset[int]]]:
    """Resolve all ship fire simultaneously against the pre-combat snapshot.

    Simultaneity rule: every attacker fires against `battle` (the snapshot);
    damage from all events is accumulated per target and applied in one pass.

    Returns (new_battle, events, new_revealed_systems).
    """
    snapshot   = battle
    all_events: list[FireEvent] = []

    damage_by_target: dict[ShipID, list] = {}
    needle_by_target: dict[ShipID, list[int]] = {}   # system indices to destroy
    ammo_by_attacker: dict[ShipID, int] = {}

    for ship_id, order in fire_orders.items():
        if order is None:
            continue
        target_id = order.target_id
        if ship_id not in snapshot.ships or target_id not in snapshot.ships:
            continue
        try:
            _, events = resolve_fire_all(
                snapshot,
                attacker_id=ship_id,
                target_id=target_id,
                rng=rng,
            )
        except (ValueError, KeyError):
            continue

        all_events.extend(events)
        for ev in events:
            if ev.hit and ev.raw_damage > 0:
                if ev.needle_target_idx is not None:
                    needle_by_target.setdefault(ev.target_id, []).append(ev.needle_target_idx)
                else:
                    damage_by_target.setdefault(ev.target_id, []).append(
                        (ev.raw_damage, WEAPONS[ev.weapon])
                    )
            if ev.ammo_consumed > 0:
                ammo_by_attacker[ship_id] = ammo_by_attacker.get(ship_id, 0) + ev.ammo_consumed

    # Apply all accumulated standard damage to each target
    new_battle = snapshot
    for target_id, damages in damage_by_target.items():
        ship = new_battle.ships[target_id]
        if ship.systems is None:
            continue
        new_systems = ship.systems
        for dmg, spec in damages:
            new_systems = new_systems.apply_weapon_damage(dmg, weapon=spec)
        new_battle = new_battle.with_ship(dataclasses.replace(ship, systems=new_systems))

    # Apply needle beam hits (destroy specific pre-computed system indices)
    for target_id, indices in needle_by_target.items():
        if target_id not in new_battle.ships:
            continue
        ship = new_battle.ships[target_id]
        if ship.systems is None:
            continue
        new_systems = ship.systems
        for idx in indices:
            new_systems = new_systems.destroy_system_at(idx)
        new_battle = new_battle.with_ship(dataclasses.replace(ship, systems=new_systems))

    # Apply ammo consumption to attackers.
    # Cap consumed against the snapshot's available ammo: fire was resolved
    # against the snapshot, so consumption cannot legitimately exceed what
    # was available at that instant.  This prevents a bug elsewhere from
    # silently consuming ammo that didn't exist.
    for attacker_id, consumed in ammo_by_attacker.items():
        if attacker_id not in new_battle.ships:
            continue
        ship = new_battle.ships[attacker_id]
        if ship.systems is None:
            continue
        snap_ship = snapshot.ships.get(attacker_id)
        if snap_ship is not None and snap_ship.systems is not None:
            available = snap_ship.systems.ammo_count_for("R")
            consumed = min(consumed, available)
        if consumed > 0:
            new_systems = ship.systems.consume_ammo_for("R", consumed)
            new_battle = new_battle.with_ship(dataclasses.replace(ship, systems=new_systems))

    # Reveal weapon systems that fired (indices on the snapshot track).
    new_revealed: dict[str, frozenset[int]] = dict(revealed_systems)
    for ev in all_events:
        if not isinstance(ev, FireEvent):
            continue
        attacker = snapshot.ships.get(ev.attacker_id)
        if attacker is None or attacker.systems is None:
            continue
        weapon_base = ev.weapon.value
        indices = set(new_revealed.get(ev.attacker_id, frozenset()))
        for i, sys in enumerate(attacker.systems):
            if sys.is_active() and sys.base == weapon_base:
                indices.add(i)
        new_revealed[ev.attacker_id] = frozenset(indices)

    # Detect ships destroyed by fire this phase.
    from tactical.events import DestructionCause, UnitDestroyedEvent
    for target_id in set(damage_by_target) | set(needle_by_target):
        if target_id not in new_battle.ships:
            continue
        ship = new_battle.ships[target_id]
        if ship.systems is not None and ship.systems.is_destroyed():
            all_events.append(UnitDestroyedEvent(target_id, DestructionCause.ENEMY_FIRE))

    return new_battle, all_events, new_revealed

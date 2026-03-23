"""Standalone movement resolution for the tactical encounter.

Called by Encounter._resolve_movement; separated to keep encounter.py concise.
"""
from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from sim.hexgrid import Hex, hex_distance
from tactical.battle_state import BattleState, ShipID
from tactical.initiative import Initiative, RNG
from tactical.turn_orders import ShipMoveOrder

if TYPE_CHECKING:
    from tactical.fighter_events import FighterCombatEvent


def resolve_movement(
    battle: BattleState,
    move_orders: dict[ShipID, ShipMoveOrder],
    launch_orders: dict[str, list],
    initiative: Initiative,
    rng: RNG,
) -> tuple[BattleState, list["FighterCombatEvent"]]:
    """Resolve simultaneous movement for all ships.

    Processes carrier launches first, then applies ship movement with conflict
    resolution (higher initiative wins contested hexes).  Checks each ship's
    movement path for transited enemy squadrons and fires a free attack run for
    each transit.

    Returns (new_battle, events) where events contains LaunchEvents, transit
    AttackRunEvents, and any UnitDestroyedEvents caused by them.
    """
    from tactical.events import DestructionCause, LaunchEvent, UnitDestroyedEvent
    from tactical.fighter_combat import resolve_attack_run

    # Process carrier launches before ship movement.
    launch_events: list = []
    new_battle = battle
    for carrier_id, launches in launch_orders.items():
        if carrier_id not in new_battle.ships:
            continue
        carrier = new_battle.ships[carrier_id]
        for lo in launches:
            sq_id = lo.squadron_id
            if sq_id not in new_battle.squadrons:
                continue
            sq = new_battle.squadrons[sq_id]
            if carrier.systems is not None:
                new_sys = carrier.systems.undock_squadron(sq_id)
                carrier = dataclasses.replace(carrier, systems=new_sys)
                new_battle = new_battle.with_ship(carrier)
            new_sq = sq.undock(carrier.pos)
            new_battle = new_battle.with_squadron(new_sq)
            launch_events.append(LaunchEvent(carrier_id=carrier_id, squadron_id=sq_id, pos=carrier.pos))

    ships = new_battle.ships

    # Desired destination for each ship (default: stay in place)
    desired: dict[ShipID, Hex] = {sid: s.pos for sid, s in ships.items()}
    for ship_id, order in move_orders.items():
        desired[ship_id] = order.dest

    # Find destination conflicts
    dest_to_ships: dict[Hex, list[ShipID]] = {}
    for sid, dest in desired.items():
        dest_to_ships.setdefault(dest, []).append(sid)

    # Resolve conflicts: higher initiative wins, losers are cancelled
    cancelled: set[ShipID] = set()
    for dest, claimants in dest_to_ships.items():
        if len(claimants) <= 1:
            continue
        ranked = sorted(
            claimants,
            key=lambda sid: initiative.rolls.get(ships[sid].owner_id, 0),
            reverse=True,
        )
        for loser in ranked[1:]:
            cancelled.add(loser)

    # Apply movement for non-cancelled ships that submitted orders
    new_ships = dict(ships)
    for ship_id, order in move_orders.items():
        if ship_id in cancelled:
            continue
        ship = new_ships[ship_id]
        cost = order.total_mp_cost or hex_distance(ship.pos, order.dest)
        new_ships[ship_id] = dataclasses.replace(
            ship,
            pos         = order.dest,
            facing      = order.dest_facing,
            mp          = max(0, ship.mp - cost),
            turn_charge = order.final_turn_charge,
        )

    new_battle = dataclasses.replace(new_battle, ships=new_ships)

    # Transit attack run detection.
    # Squadron positions are fixed during MOVE_SUBMISSION; use pre-movement
    # positions from the original battle snapshot.
    transit_events: list = []
    if battle.squadrons:
        for ship_id, order in move_orders.items():
            if ship_id in cancelled:
                continue
            orig_ship = battle.ships[ship_id]
            transit_hexes: tuple[Hex, ...] = (
                order.path[1:] if len(order.path) > 1 else (order.dest,)
            )
            seen_hexes: set[Hex] = set()
            for hex_pos in transit_hexes:
                if hex_pos in seen_hexes:
                    continue
                seen_hexes.add(hex_pos)
                for sq_id, sq in battle.squadrons.items():
                    if sq.owner_id == orig_ship.owner_id:
                        continue
                    if sq.pos != hex_pos:
                        continue
                    if ship_id not in new_battle.ships:
                        continue
                    if sq_id not in new_battle.squadrons:
                        continue
                    new_battle, ev = resolve_attack_run(
                        new_battle,
                        attacker_id=sq_id,
                        target_ship_id=ship_id,
                        rng=rng,
                        simultaneous=True,
                    )
                    transit_events.append(ev)

                    if sq_id not in new_battle.squadrons:
                        transit_events.append(
                            UnitDestroyedEvent(sq_id, DestructionCause.POINT_DEFENSE)
                        )
                    if ship_id in new_battle.ships:
                        s = new_battle.ships[ship_id]
                        if s.systems is not None and s.systems.is_destroyed():
                            transit_events.append(
                                UnitDestroyedEvent(ship_id, DestructionCause.ENEMY_FIRE)
                            )

    return new_battle, launch_events + transit_events

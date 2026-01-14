from __future__ import annotations

from tactical.battle_state import BattleState


def refresh_mp_for_new_tactical_turn(battle: BattleState, mp_by_ship_id: dict[str, int]) -> BattleState:
    """Return a new BattleState with ship.mp refreshed for a new TacticalTurn.

    Does NOT modify turn_charge (per your rule).
    """
    new_ships = dict(battle.ships)
    for ship_id, ship in battle.ships.items():
        if ship_id not in mp_by_ship_id:
            raise KeyError(f"Missing mp value for ship_id={ship_id!r}")
        new_ships[ship_id] = type(ship)(
            ship_id=ship.ship_id,
            owner_id=ship.owner_id,
            pos=ship.pos,
            facing=ship.facing,
            mp=int(mp_by_ship_id[ship_id]),
            turn_cost=ship.turn_cost,
            turn_charge=ship.turn_charge,  # persists!
            track=ship.systems,
        )
    return BattleState(new_ships)

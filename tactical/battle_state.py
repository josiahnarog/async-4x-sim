from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sim.hexgrid import Hex
from tactical.ship_state import ShipState


ShipID = str


@dataclass(frozen=True, slots=True)
class BattleState:
    """Minimal tactical battle state (MVP).

    Responsibilities:
      - own ships and their tactical state
      - enforce destination-occupancy rule for ship movement
      - provide deterministic iteration ordering
    """

    ships: dict[ShipID, ShipState]

    # ---------------------------------------------------------------------
    # Deterministic views
    # ---------------------------------------------------------------------

    def ship_ids_sorted(self) -> list[ShipID]:
        """Stable ordering: by (q, r, ship_id) to keep tests deterministic."""
        return sorted(self.ships.keys(), key=lambda sid: (self.ships[sid].pos.q, self.ships[sid].pos.r, sid))

    def ships_sorted(self) -> list[ShipState]:
        return [self.ships[sid] for sid in self.ship_ids_sorted()]

    # ---------------------------------------------------------------------
    # Occupancy
    # ---------------------------------------------------------------------

    def occupied_hexes(self, *, exclude: Iterable[ShipID] = ()) -> set[Hex]:
        ex = set(exclude)
        return {s.pos for sid, s in self.ships.items() if sid not in ex}

    def is_occupied(self, hex_: Hex, *, exclude: Iterable[ShipID] = ()) -> bool:
        return hex_ in self.occupied_hexes(exclude=exclude)

    # ---------------------------------------------------------------------
    # Mutations (pure)
    # ---------------------------------------------------------------------

    def with_ship(self, ship: ShipState) -> BattleState:
        new_ships = dict(self.ships)
        new_ships[ship.ship_id] = ship
        return BattleState(new_ships)

    def move_ship_forward(self, ship_id: ShipID, steps: int = 1) -> BattleState:
        """Move a ship forward with battle-wide occupancy enforcement.

        Occupancy rule (MVP):
          - ships may pass through occupied hexes
          - ships may NOT end movement in an occupied hex

        We enforce this by giving ShipState the occupied set excluding itself.
        """
        if ship_id not in self.ships:
            raise KeyError(f"Unknown ship_id: {ship_id}")

        ship = self.ships[ship_id]
        occupied = self.occupied_hexes(exclude=[ship_id])
        moved = ship.move_forward(steps, occupied=occupied)
        return self.with_ship(moved)

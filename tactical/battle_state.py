from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Iterable

from sim.hexgrid import Hex
from tactical.ship_state import ShipState
from tactical.squadron_state import SquadronID, SquadronState


ShipID = str


@dataclass(frozen=True, slots=True)
class BattleState:
    """Minimal tactical battle state.

    Owns both capital ships and fighter squadrons.  Squadrons are
    facing-less and do not participate in the ship occupancy rules —
    capital ships may share a hex with squadrons freely.
    """

    ships:     dict[ShipID,     ShipState]
    squadrons: dict[SquadronID, SquadronState] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Deterministic views
    # ------------------------------------------------------------------

    def ship_ids_sorted(self) -> list[ShipID]:
        """Stable ordering: by (q, r, ship_id) to keep tests deterministic."""
        return sorted(
            self.ships.keys(),
            key=lambda sid: (self.ships[sid].pos.q, self.ships[sid].pos.r, sid),
        )

    def ships_sorted(self) -> list[ShipState]:
        return [self.ships[sid] for sid in self.ship_ids_sorted()]

    def squadron_ids_sorted(self) -> list[SquadronID]:
        return sorted(
            self.squadrons.keys(),
            key=lambda sqid: (
                self.squadrons[sqid].pos.q,
                self.squadrons[sqid].pos.r,
                sqid,
            ),
        )

    def squadrons_sorted(self) -> list[SquadronState]:
        return [self.squadrons[sqid] for sqid in self.squadron_ids_sorted()]

    # ------------------------------------------------------------------
    # Occupancy (ships only — squadrons do not block ship movement)
    # ------------------------------------------------------------------

    def ship_occupied_hexes(self, *, exclude: Iterable[ShipID] = ()) -> set[Hex]:
        ex = set(exclude)
        return {s.pos for sid, s in self.ships.items() if sid not in ex}

    def is_ship_occupied(self, hex_: Hex, *, exclude: Iterable[ShipID] = ()) -> bool:
        return hex_ in self.ship_occupied_hexes(exclude=exclude)

    # ------------------------------------------------------------------
    # Engagement helpers
    # ------------------------------------------------------------------

    def squadrons_at(self, hex_: Hex) -> list[SquadronState]:
        """All squadrons (any owner) at a given hex."""
        return [sq for sq in self.squadrons.values() if sq.pos == hex_]

    def engaged_squadrons(self) -> list[tuple[SquadronState, list[SquadronState]]]:
        """Return (squadron, enemy_squadrons_in_same_hex) for every squadron
        that has at least one enemy in its hex."""
        result = []
        for sq in self.squadrons.values():
            enemies = [
                other for other in self.squadrons_at(sq.pos)
                if other.owner_id != sq.owner_id
            ]
            if enemies:
                result.append((sq, enemies))
        return result

    # ------------------------------------------------------------------
    # Mutations (pure)
    # ------------------------------------------------------------------

    def with_ship(self, ship: ShipState) -> BattleState:
        new_ships = {**self.ships, ship.ship_id: ship}
        return dataclasses.replace(self, ships=new_ships)

    def with_squadron(self, sq: SquadronState) -> BattleState:
        new_squads = {**self.squadrons, sq.squadron_id: sq}
        return dataclasses.replace(self, squadrons=new_squads)

    def without_squadron(self, squadron_id: SquadronID) -> BattleState:
        new_squads = {k: v for k, v in self.squadrons.items() if k != squadron_id}
        return dataclasses.replace(self, squadrons=new_squads)

    def move_ship_forward(self, ship_id: ShipID, steps: int = 1) -> BattleState:
        """Move a ship forward with battle-wide occupancy enforcement."""
        if ship_id not in self.ships:
            raise KeyError(f"Unknown ship_id: {ship_id}")
        ship = self.ships[ship_id]
        occupied = self.ship_occupied_hexes(exclude=[ship_id])
        moved = ship.move_forward(steps, occupied=occupied)
        return self.with_ship(moved)

"""Ship instance — a design with live, mutable system state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ships.design import ShipDesign
from tactical.ship_systems import ShipSystems

if TYPE_CHECKING:
    from tactical.hull_types import HullType
    from tactical.ship_state import ShipState


@dataclass
class ShipInstance:
    instance_id: str
    design:      ShipDesign
    systems:     ShipSystems

    @staticmethod
    def from_design(design: ShipDesign, instance_id: str) -> ShipInstance:
        """Create a fresh instance from a design with all systems intact."""
        return ShipInstance(
            instance_id=instance_id,
            design=design,
            systems=ShipSystems.parse(design.systems_str),
        )

    @property
    def hull_type(self) -> HullType:
        from tactical.hull_types import HULL_TYPES
        return HULL_TYPES[self.design.hull_type_id]

    @property
    def active_speed(self) -> int:
        """Current tactical MP capacity, reflecting any engine damage."""
        ht = self.hull_type
        return ht.movement_points(self.systems._active_engine_count())

    def to_ship_state(
        self,
        ship_id: str,
        owner_id: str,
        pos,     # sim.hexgrid.Hex
        facing,  # tactical.facing.Facing
    ) -> ShipState:
        """Create a ShipState for loading this instance into a tactical encounter."""
        from tactical.ship_state import ShipState
        ht = self.hull_type
        return ShipState(
            ship_id=ship_id,
            owner_id=owner_id,
            pos=pos,
            facing=facing,
            mp=ht.movement_points(self.systems._active_engine_count()),
            turn_cost=ht.turn_cost,
            systems=self.systems,
            hull_type=ht,
        )

    def apply_encounter_result(self, ship_state: ShipState) -> None:
        """Update live system state from a completed tactical encounter."""
        if ship_state.systems is not None:
            self.systems = ship_state.systems

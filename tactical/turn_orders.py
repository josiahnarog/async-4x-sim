from __future__ import annotations

from dataclasses import dataclass

from sim.hexgrid import Hex
from tactical.battle_state import ShipID
from tactical.facing import Facing


@dataclass(frozen=True, slots=True)
class ShipMoveOrder:
    """A ship's submitted movement order for the MOVE_SUBMISSION phase."""
    dest: Hex
    dest_facing: Facing


@dataclass(frozen=True, slots=True)
class ShipFireOrder:
    """A ship's submitted fire order for the COMBAT_SUBMISSION phase."""
    target_id: ShipID

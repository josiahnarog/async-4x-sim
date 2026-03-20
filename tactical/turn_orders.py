from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from sim.hexgrid import Hex
from tactical.battle_state import ShipID
from tactical.facing import Facing


# ---------------------------------------------------------------------------
# Capital ship orders
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ShipMoveOrder:
    """A ship's submitted movement order for the MOVE_SUBMISSION phase.

    path: ordered sequence of hexes traversed (including start and dest).
    Used during movement resolution to detect transit through enemy-held hexes.
    If empty, only the destination hex is checked for transit interceptions.
    """
    dest: Hex
    dest_facing: Facing
    path: tuple[Hex, ...] = dataclasses.field(default_factory=tuple)
    total_mp_cost: int = 0   # total MP consumed (hex distance + turning cost)


@dataclass(frozen=True, slots=True)
class ShipFireOrder:
    """A ship's submitted fire order for the COMBAT_SUBMISSION phase."""
    target_id: ShipID


# ---------------------------------------------------------------------------
# Fighter squadron orders  (COMBAT_SMALL phase)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class InterceptOrder:
    """Move to patrol_hex then intercept any enemy within (remaining_mp + 1) hexes.

    intercept_radius is computed at resolution time as:
        (squadron.effective_mp - hex_distance(start, patrol_hex)) + 1
    """
    patrol_hex: Hex


@dataclass(frozen=True, slots=True)
class StrikeOrder:
    """Vector toward target_id (a ShipID or SquadronID) and engage on contact.

    - If the target is an enemy squadron  → dogfight on arrival.
    - If the target is an enemy ship      → attack run on arrival.

    The squadron moves as far as its effective_mp allows toward the target.
    If it can reach the target this turn, engagement resolves immediately.
    """
    target_id: str  # ShipID or SquadronID


@dataclass(frozen=True, slots=True)
class BreakOffOrder:
    """Attempt to disengage from a dogfight and move to dest.

    The squadron takes a parting shot from each enemy squadron sharing its
    hex before moving.  If dest is unreachable within effective_mp the
    squadron moves as far as possible toward dest instead.
    """
    dest: Hex


# Convenience type alias used in Encounter
SquadronOrder = InterceptOrder | StrikeOrder | BreakOffOrder

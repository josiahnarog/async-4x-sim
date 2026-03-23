from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Optional

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

    final_turn_charge: the turn_charge the ship should have after movement
    resolves.  Set at staging time (from draft state or computed analytically
    for direct-hex moves) so _resolve_movement() can apply it precisely rather
    than approximating via modular arithmetic.
    """
    dest: Hex
    dest_facing: Facing
    path: tuple[Hex, ...] = dataclasses.field(default_factory=tuple)
    total_mp_cost: int = 0   # total MP consumed (hex distance + turning cost)
    final_turn_charge: int = 0  # turn_charge to restore after this move resolves


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
    If max_intercept_radius is set, the radius is capped to that value.
    """
    patrol_hex: Hex
    max_intercept_radius: Optional[int] = None


@dataclass(frozen=True, slots=True)
class MoveOrder:
    """Move to dest hex without intercepting.

    The squadron moves as far as its effective_mp allows toward dest.
    No intercept engagement occurs — use InterceptOrder for patrolling.
    """
    dest: Hex


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


@dataclass(frozen=True, slots=True)
class LaunchOrder:
    """Carrier launches a docked squadron. Staged alongside ship movement orders."""
    squadron_id: str   # SquadronID


@dataclass(frozen=True, slots=True)
class RecoverOrder:
    """Squadron requests recovery aboard carrier_id at the current hex."""
    carrier_id: str   # ShipID


# Convenience type alias used in Encounter
SquadronOrder = InterceptOrder | MoveOrder | StrikeOrder | BreakOffOrder | RecoverOrder

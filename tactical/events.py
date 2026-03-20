"""Shared event types emitted by tactical resolution functions."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DestructionCause(str, Enum):
    ENEMY_FIRE    = "enemy fire"
    DOGFIGHT      = "dogfight"
    POINT_DEFENSE = "point defense"
    FUEL_EXHAUSTED = "fuel exhausted"


@dataclass(frozen=True, slots=True)
class UnitDestroyedEvent:
    unit_id: str
    cause:   DestructionCause


@dataclass(frozen=True, slots=True)
class FuelWarningEvent:
    """Emitted at turn end when a squadron has exactly 1 turn of fuel remaining.

    The squadron will be destroyed at the end of the *next* turn unless it
    lands on a carrier before then.
    """
    squadron_id: str


@dataclass(frozen=True, slots=True)
class BattleEndEvent:
    """Emitted when the battle is over (one or both sides have no ships left).

    surviving_sides: the set of side IDs that still have at least one
    non-destroyed ship.  Empty = mutual destruction (draw).
    """
    surviving_sides: frozenset

    @property
    def is_draw(self) -> bool:
        return len(self.surviving_sides) == 0

    @property
    def winner(self) -> str | None:
        """Returns the winning side ID, or None for a draw."""
        if len(self.surviving_sides) == 1:
            return next(iter(self.surviving_sides))
        return None

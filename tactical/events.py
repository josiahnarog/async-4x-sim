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

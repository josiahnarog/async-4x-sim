from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TargetClass(str, Enum):
    SHIP = "ship"
    SMALL_CRAFT = "small_craft"
    MISSILE = "missile"


@dataclass(frozen=True, slots=True)
class ToHitMod:
    """
    Modifiers affecting to-hit resolution.

    Interpretation (d10, hit if roll <= target):
      - range_shift: adjusts effective range used for table lookup
          +1 => treat target as further away => usually harder (table likely lower)
          -1 => treat as closer => usually easier

      - target_delta: adjusts the *to-hit target number*
          +1 => easier (bigger target)
          -1 => harder (smaller target)

      - roll_delta: adjusts the rolled value
          +1 => harder (roll increases)
          -1 => easier (roll decreases)

    Multiple modifiers combine by summing each field deterministically.
    """
    range_shift: int = 0
    target_delta: int = 0
    roll_delta: int = 0


@dataclass(frozen=True, slots=True)
class AttackContext:
    """
    Context passed into to-hit calculation.

    base_range: geometric distance (or abstract range) before modifiers
    effective_range: base_range + summed range_shift, clamped >= 0

    target_class: what we're trying to hit (ship / missile / small craft)
    """
    target_class: TargetClass
    base_range: int
    effective_range: int

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class HullType:
    designation: str          # e.g. "FG"
    name: str                 # e.g. "Frigate"
    engine_power_ratio: Fraction  # MP granted per active engine system
    engines_per_room: int     # number of I systems that form one engine room (parentheses cluster)
    max_speed: int            # hard cap on MP capacity per subphase refresh

    def movement_points(self, active_engine_count: int) -> int:
        """MP capacity from engine count, floored and capped at max_speed."""
        raw = int(active_engine_count / self.engine_power_ratio)
        return min(raw, self.max_speed)


FG = HullType(
    designation="FG",
    name="Frigate",
    engine_power_ratio=Fraction(2, 3),
    engines_per_room=3,
    max_speed=5,
)

DD = HullType(
    designation="DD",
    name="Destroyer",
    engine_power_ratio=Fraction(1, 1),
    engines_per_room=2,
    max_speed=5,
)

CA = HullType(
    designation="CA",
    name="Cruiser",
    engine_power_ratio=Fraction(2, 1),
    engines_per_room=1,
    max_speed=4,
)

CV = HullType(
    designation="CV",
    name="Carrier",
    engine_power_ratio=Fraction(2, 1),   # same EPR as CA
    engines_per_room=1,
    max_speed=4,
    # turn_cost=3 is set on ShipState at instantiation
)

HULL_TYPES: dict[str, HullType] = {h.designation: h for h in (FG, DD, CA, CV)}

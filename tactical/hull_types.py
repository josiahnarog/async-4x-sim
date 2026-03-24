from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from tactical.ship_catalog import HULL_CATALOG, hull_engines_per_room


@dataclass(frozen=True)
class HullType:
    designation: str          # e.g. "FG"
    name: str                 # e.g. "Frigate"
    engine_power_ratio: Fraction  # MP granted per active engine system
    engines_per_room: int     # number of I systems that form one engine room
    max_speed: int            # hard cap on MP capacity per subphase refresh
    turn_cost: int            # MP that must be spent to earn one facing change

    def movement_points(self, active_engine_count: int) -> int:
        """MP capacity from engine count, floored and capped at max_speed."""
        raw = int(active_engine_count / self.engine_power_ratio)
        return min(raw, self.max_speed)


def _build_hull_types() -> dict[str, HullType]:
    result = {}
    for h in HULL_CATALOG:
        if h.max_speed is None or h.turn_cost is None:
            continue  # skip immobile hulls not yet fully implemented
        result[h.designation] = HullType(
            designation=h.designation,
            name=h.name,
            engine_power_ratio=Fraction(h.epr_i),
            engines_per_room=hull_engines_per_room(h),
            max_speed=h.max_speed,
            turn_cost=h.turn_cost,
        )
    return result


HULL_TYPES: dict[str, HullType] = _build_hull_types()

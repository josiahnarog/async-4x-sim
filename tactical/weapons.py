from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional, Union


MAX_RANGE = 50


@dataclass(frozen=True, slots=True)
class RangeTable:
    """Lookup table for ranges 0..MAX_RANGE.

    If fewer than 51 values are provided, we extend by repeating the last value.
    """
    values: tuple[Optional[int], ...]

    @staticmethod
    def from_list(vals: Iterable[Union[int, str, None]]) -> RangeTable:
        """Create a RangeTable from ints and/or '-' sentinels.

        '-' or None means "not possible" (e.g., cannot hit beyond this range).
        """
        base_list: list[Optional[int]] = []
        for v in vals:
            if v is None:
                base_list.append(None)
                continue
            if isinstance(v, str):
                s = v.strip()
                if s == "-":
                    base_list.append(None)
                    continue
                base_list.append(int(s))
                continue
            base_list.append(int(v))

        base = tuple(base_list)
        if not base:
            raise ValueError("RangeTable requires at least one value")
        if len(base) < MAX_RANGE + 1:
            base = base + (base[-1],) * (MAX_RANGE + 1 - len(base))
        elif len(base) > MAX_RANGE + 1:
            base = base[: MAX_RANGE + 1]
        return RangeTable(values=base)

    def at(self, rng: int) -> Optional[int]:
        if rng < 0:
            raise ValueError("range must be >= 0")
        if rng > MAX_RANGE:
            rng = MAX_RANGE
        return self.values[rng]


class WeaponType(str, Enum):
    ELECTRON_BEAM = "E"  # Electron Beam
    LASER = "L"          # Laser
    FORCE_BEAM = "F"     # Force Beam (baseline example)
    STANDARD_MISSILE = "R"  # Standard Missile


@dataclass(frozen=True, slots=True)
class WeaponSpec:
    type: WeaponType
    name: str
    rate_of_fire: int
    to_hit: RangeTable
    damage: RangeTable

    # Damage application rules:
    skip_codes: frozenset[str] = frozenset()   # codes skipped entirely by this weapon
    shield_multiplier: float = 1.0             # e.g. Electron Beam = 0.5 against shields

    def damage_at(self, rng: int) -> int:
        v = self.damage.at(rng)
        assert v is not None
        return v

    def to_hit_at(self, rng: int) -> Optional[int]:
        return self.to_hit.at(rng)


ELECTRON_BEAM = WeaponSpec(
    type=WeaponType.ELECTRON_BEAM,
    name="Electron Beam",
    rate_of_fire=1,
    # Provided 7 values; extend to 0..50 by repeating last
    to_hit=RangeTable.from_list([7, 7, 7, 6, 6, 6, 6]),
    damage=RangeTable.from_list([3, 3, 2, 2, 2, 1, 1]),
    # Electron Beam skips Armor and Hull
    skip_codes=frozenset({"A", "H"}),
    # Half damage vs shields (rounded down per point application)
    shield_multiplier=0.5,
)

LASER = WeaponSpec(
    type=WeaponType.LASER,
    name="Laser",
    rate_of_fire=1,
    to_hit=RangeTable.from_list([8, 8, 8, 7, 7, 7, 7]),
    damage=RangeTable.from_list([2, 2, 2, 1, 1, 1, 1]),
    # Laser skips shields
    skip_codes=frozenset({"S"}),
)

FORCE_BEAM = WeaponSpec(
    type=WeaponType.FORCE_BEAM,
    name="Force Beam",
    rate_of_fire=1,
    # Placeholder baseline; you can replace later
    to_hit=RangeTable.from_list([7]),
    damage=RangeTable.from_list([2]),
)

STANDARD_MISSILE = WeaponSpec(
    type=WeaponType.STANDARD_MISSILE,
    name="Standard Missile",
    rate_of_fire=1,
    # '-' means "cannot hit beyond this range"; extended to 0..50 by repeating '-'.
    to_hit=RangeTable.from_list([6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 5, 5, 4, 4, 3, 3, "-"]),
    # 1 damage at all ranges
    damage=RangeTable.from_list([1]),
)


WEAPONS: dict[WeaponType, WeaponSpec] = {
    WeaponType.ELECTRON_BEAM: ELECTRON_BEAM,
    WeaponType.LASER: LASER,
    WeaponType.FORCE_BEAM: FORCE_BEAM,
    WeaponType.STANDARD_MISSILE: STANDARD_MISSILE,
}

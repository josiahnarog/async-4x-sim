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
    ELECTRON_BEAM    = "E"  # Electron Beam
    LASER            = "L"  # Laser
    FORCE_BEAM       = "F"  # Force Beam
    NEEDLE_BEAM      = "N"  # Needle Beam — penetrates shields/armor; random deep system hit
    STANDARD_MISSILE = "R"  # Standard Missile
    GUN              = "G"  # Autocannon — fighter primary weapon, +2 vs fighters
    RAIL_GUN         = "K"  # Rail Gun (Kinetic) — high close-range damage, no special rules


class WeaponArc(Enum):
    """Defines which arcs a weapon can fire into (on top of the global blind-spot rule).

    ALL     — can fire into any non-blind-spot bearing (relative bearings 0, 1, 5).
    FORWARD — can only fire dead ahead (relative bearing 0).
    """
    ALL     = "all"
    FORWARD = "forward"


# Sentinel meaning "bypass all systems of this type".
SKIP_ALL = 0x7FFF_FFFF


@dataclass(frozen=True, slots=True)
class SkipRule:
    """Defines how many active systems of each type a weapon bypasses before dealing damage.

    The first `shields` active S systems on the track are skipped entirely.
    The first `armor`   active A systems on the track are skipped entirely.
    The first `holds`   active B systems (Bh, Bl) on the track are skipped entirely.

    Use SKIP_ALL to bypass all systems of that type (e.g. Laser skips all shields).
    Multipliers (shield_multiplier / armor_multiplier on WeaponSpec) are still applied
    to the *first eligible* system of that type after any skips.

    All fields must be >= 0.  SKIP_ALL is the only legitimate large value.
    """
    shields: int = 0
    armor: int = 0
    holds: int = 0

    def __post_init__(self) -> None:
        for name, val in (("shields", self.shields), ("armor", self.armor), ("holds", self.holds)):
            if val < 0:
                raise ValueError(f"SkipRule.{name} must be >= 0, got {val!r}")


@dataclass(frozen=True, slots=True)
class WeaponSpec:
    type: WeaponType
    name: str
    rate_of_fire: int
    to_hit: RangeTable
    damage: RangeTable

    # Skip rules: how many of each system type are bypassed before damage is applied.
    skip: SkipRule = SkipRule()

    # Damage multipliers applied when the next eligible system is of that type.
    # 0.5 = half the remaining damage points (floor), 1.0 = no change.
    shield_multiplier: float = 1.0
    armor_multiplier: float = 1.0

    # Firing arc restriction (in addition to the universal blind-spot rule):
    firing_arc: WeaponArc = WeaponArc.ALL

    # Ammunition: if True, weapon consumes charges from its system (or a magazine).
    requires_ammo: bool = False

    # Fighter combat rules:
    anti_fighter_modifier: int = 0   # added to to-hit when attacking a squadron
    can_target_fighters: bool = True  # False = weapon cannot engage squadrons

    # Needle beam penetration (separate mechanic — target selection, not damage).
    # Value = how many combined S/A systems are bypassed before the random system roll.
    needle_skip: int = 0

    # Ordnance penalties applied to any fighter carrying this weapon externally.
    # ordnance_mp_penalty  — flat MP reduction while at least one shot of this
    #                        weapon type remains loaded on the fighter.
    # ordnance_mvr_penalty_per_shot — MVR reduction per remaining external shot
    #                                 of this weapon type.
    ordnance_mp_penalty: int = 0
    ordnance_mvr_penalty_per_shot: int = 0

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
    to_hit=RangeTable.from_list([7, 7, 7, 6, 6, 6, 6]),
    damage=RangeTable.from_list([3, 3, 2, 2, 2, 1, 1]),
    # Bypasses all armor; half damage vs shields
    skip=SkipRule(armor=SKIP_ALL),
    shield_multiplier=0.5,
)

LASER = WeaponSpec(
    type=WeaponType.LASER,
    name="Laser",
    rate_of_fire=1,
    to_hit=RangeTable.from_list([8, 8, 8, 7, 7, 7, "-"]),
    damage=RangeTable.from_list([2, 2, 2, 1, 1, 1, "-"]),
    # Bypasses all shields — hits armor directly
    skip=SkipRule(shields=SKIP_ALL),
)

FORCE_BEAM = WeaponSpec(
    type=WeaponType.FORCE_BEAM,
    name="Force Beam",
    rate_of_fire=1,
    to_hit=RangeTable.from_list([8, 8, 8, 7, 7, 7, 7, 6, "-"]),
    damage=RangeTable.from_list([3, 2, 2, 2, 1, 1, 1, 1, "-"]),
    # No skip rules — hits shields first like normal fire
)

NEEDLE_BEAM = WeaponSpec(
    type=WeaponType.NEEDLE_BEAM,
    name="Needle Beam",
    rate_of_fire=1,
    to_hit=RangeTable.from_list([8, 8, 8, 7, 7, 7, 6, 6, 5, "-"]),
    # Always destroys exactly 1 system; damage field unused for needle beams
    # but must be non-None so damage_at() doesn't crash.
    damage=RangeTable.from_list([1]),
    can_target_fighters=False,
    # Needle beam uses a separate penetration mechanic (needle_skip), not SkipRule.
    # skip.shields/armor/holds are left at 0 — apply_weapon_damage is not called for needle hits.
    needle_skip=30,
)

STANDARD_MISSILE = WeaponSpec(
    type=WeaponType.STANDARD_MISSILE,
    name="Standard Missile",
    rate_of_fire=1,
    to_hit=RangeTable.from_list([6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 5, 5, 4, 4, 3, 3, "-"]),
    damage=RangeTable.from_list([1]),
    requires_ammo=True,
    can_target_fighters=False,
    # Ordnance penalties: a loaded missile slows and unmaneuverable fighters.
    ordnance_mp_penalty=2,          # -2 MP flat while any R remains loaded
    ordnance_mvr_penalty_per_shot=1, # -1 MVR per R shot still carried
)

GUN = WeaponSpec(
    type=WeaponType.GUN,
    name="Gun",
    rate_of_fire=1,
    to_hit=RangeTable.from_list([8, 8, 8, 7, 7, "-"]),
    damage=RangeTable.from_list([2, 2, 1, 1, 1, "-"]),
    # Half damage vs shields and armor — effective against exposed systems
    shield_multiplier=0.5,
    armor_multiplier=0.5,
    anti_fighter_modifier=2,
)


RAIL_GUN = WeaponSpec(
    type=WeaponType.RAIL_GUN,
    name="Rail Gun",
    rate_of_fire=1,
    to_hit=RangeTable.from_list([7, 7, 7, 7, 6, 6, 6, 6, 6, 6, 5, 5, 5, 5, "-"]),
    damage=RangeTable.from_list([3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, "-"]),
)


WEAPONS: dict[WeaponType, WeaponSpec] = {
    WeaponType.ELECTRON_BEAM:    ELECTRON_BEAM,
    WeaponType.LASER:            LASER,
    WeaponType.FORCE_BEAM:       FORCE_BEAM,
    WeaponType.NEEDLE_BEAM:      NEEDLE_BEAM,
    WeaponType.STANDARD_MISSILE: STANDARD_MISSILE,
    WeaponType.GUN:              GUN,
    WeaponType.RAIL_GUN:         RAIL_GUN,
}

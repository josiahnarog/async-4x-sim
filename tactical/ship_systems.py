from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Iterator, Tuple

from tactical.weapons import WeaponSpec


class SystemStatus(str, Enum):
    INTACT = "intact"
    DESTROYED = "destroyed"


@dataclass(frozen=True, slots=True)
class System:
    """A single damageable system 'system' on a ship's track.

    System tokens are camel case:
      - exactly one capital letter per system (base)
      - followed by zero or more lowercase letters (mods)

    Examples:
      S   -> shield
      A   -> armor
      L   -> laser
      Xc  -> capital sensors
    """

    base: str
    mods: str = ""
    status: SystemStatus = SystemStatus.INTACT
    group: int | None = None

    def is_active(self) -> bool:
        return self.status == SystemStatus.INTACT

    def destroy(self) -> System:
        if self.status == SystemStatus.DESTROYED:
            return self
        return System(
            base=self.base,
            mods=self.mods,
            status=SystemStatus.DESTROYED,
            group=self.group,
        )

    @property
    def token(self) -> str:
        return f"{self.base}{self.mods}"


@dataclass(frozen=True, slots=True)
class ShipSystems:
    """Canonical representation of a ship's systems.

    Ordering of systems is authoritative and used for:
      - deterministic damage application
      - rendering
      - capability queries
    """

    systems: tuple[System, ...]

    # ---------------------------------------------------------------------
    # Parsing
    # ---------------------------------------------------------------------

    @staticmethod
    def parse(compact: str) -> ShipSystems:
        """Parse a compact system-track string.

        Examples:
          SSSAAALL(III)(III)
          XcXc(III)

        Grammar (MVP):
          - token := [A-Z][a-z]*
          - parentheses group tokens but do not affect damage order
          - whitespace is ignored

        This parser assumes all systems start intact.
        """
        s = "".join(ch for ch in compact if not ch.isspace())
        systems: list[System] = []
        i = 0
        group_id = 0

        def take_token(start: int, group: int | None) -> int:
            if start >= len(s):
                raise ValueError("Expected system token at end of input")
            if not ("A" <= s[start] <= "Z"):
                raise ValueError(f"Expected system token at position {start}")

            base = s[start]
            j = start + 1
            while j < len(s) and ("a" <= s[j] <= "z"):
                j += 1

            mods = s[start + 1 : j]
            systems.append(System(base=base, mods=mods, group=group))
            return j

        while i < len(s):
            ch = s[i]

            if "A" <= ch <= "Z":
                i = take_token(i, None)
                continue

            if ch == "(":
                i += 1
                group_id += 1

                if i >= len(s) or not ("A" <= s[i] <= "Z"):
                    raise ValueError(f"Expected system token after '(' at position {i}")

                while i < len(s) and ("A" <= s[i] <= "Z"):
                    i = take_token(i, group_id)

                if i >= len(s) or s[i] != ")":
                    raise ValueError(f"Unclosed group starting near position {i}")

                i += 1
                continue

            raise ValueError(f"Unexpected character at position {i}: {ch!r}")

        if not systems:
            raise ValueError("SystemTrack cannot be empty")

        return ShipSystems(tuple(systems))

    @staticmethod
    def from_systems(systems: Iterable[System]) -> ShipSystems:
        return ShipSystems(tuple(systems))

    # ---------------------------------------------------------------------
    # Rendering / serialization
    # ---------------------------------------------------------------------

    def render_compact(self) -> str:
        """Render to compact notation.

        Destroyed systems are prefixed with '!' so lowercase
        letters remain available for system modifiers.
        """
        out: list[str] = []
        current_group: int | None = None

        def close_group() -> None:
            nonlocal current_group
            if current_group is not None:
                out.append(")")
                current_group = None

        for b in self.systems:
            if b.group != current_group:
                close_group()
                if b.group is not None:
                    out.append("(")
                    current_group = b.group

            out.append(f"!{b.token}" if b.status == SystemStatus.DESTROYED else b.token)

        close_group()
        return "".join(out)

    def to_dict(self) -> dict:
        return {
            "systems": [
                {
                    "base": b.base,
                    "mods": b.mods,
                    "status": b.status.value,
                    "group": b.group,
                }
                for b in self.systems
            ]
        }

    @staticmethod
    def from_dict(data: dict) -> ShipSystems:
        systems: list[System] = []

        for b in data.get("systems", []):
            status = SystemStatus(b.get("status", SystemStatus.INTACT.value))

            base = str(b["base"]).upper()
            if len(base) != 1 or not ("A" <= base <= "Z"):
                raise ValueError(f"Invalid base system code: {base!r}")

            mods = str(b.get("mods", ""))
            if any(not ("a" <= ch <= "z") for ch in mods):
                raise ValueError(f"Invalid system modifiers: {mods!r}")

            systems.append(
                System(
                    base=base,
                    mods=mods,
                    status=status,
                    group=b.get("group"),
                )
            )

        return ShipSystems(tuple(systems))

    # ---------------------------------------------------------------------
    # Queries
    # ---------------------------------------------------------------------

    def __iter__(self) -> Iterator[System]:
        return iter(self.systems)

    def active_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for b in self.systems:
            if b.is_active():
                counts[b.base] = counts.get(b.base, 0) + 1
        return counts

    def active_count(self, code: str) -> int:
        c = code.upper()
        return sum(1 for b in self.systems if b.is_active() and b.base == c)

    def movement_points(self, engine_code: str = "I") -> int:
        """MVP rule: each intact engine system grants 1 movement point."""
        return self.active_count(engine_code)

    # ---------------------------------------------------------------------
    # Mutation (pure, deterministic)
    # ---------------------------------------------------------------------

    def apply_damage(self, amount: int = 1) -> ShipSystems:
        """Apply damage left-to-right to intact systems.

        Returns a new SystemTrack (does not mutate).
        """
        if amount <= 0:
            return self

        remaining = amount
        new_systems: list[System] = []

        for b in self.systems:
            if remaining > 0 and b.is_active():
                new_systems.append(b.destroy())
                remaining -= 1
            else:
                new_systems.append(b)

        return ShipSystems(tuple(new_systems))

    def apply_weapon_damage(self, damage: int, *, weapon: WeaponSpec) -> "ShipSystems":
        """Apply weapon damage to this ship's systems.

        Rules (current MVP):
          - damage is applied point-by-point
          - ALWAYS skip systems that are already DESTROYED
          - weapon may skip specific base codes (e.g. Laser skips 'S', Electron skips 'A' and 'H')
          - Electron Beam: half damage vs shields (rounded down) applied as:
              when the next eligible system is a shield, reduce remaining points to floor(points * multiplier)
              before applying to shields.
            (If you instead want per-point halving, say so; this is the more “tabletop typical” interpretation.)
        """
        if damage <= 0:
            return self

        systems = list(self.systems)
        skip = set(weapon.skip_codes)

        def eligible(i: int) -> bool:
            s = systems[i]
            return s.is_active() and (s.base not in skip)

        def next_idx() -> int | None:
            for i in range(len(systems)):
                if eligible(i):
                    return i
            return None

        points = int(damage)

        while points > 0:
            idx = next_idx()
            if idx is None:
                break

            if systems[idx].base == "S" and weapon.shield_multiplier != 1.0:
                points = int(points * weapon.shield_multiplier)  # floor
                if points <= 0:
                    break

            systems[idx] = systems[idx].destroy()
            points -= 1

        return ShipSystems(tuple(systems))

    def point_defense(self) -> Tuple[int, int]:
        """
        Returns (shots, to_hit) for point defense for the current incoming volley.

        Each intact 'D' system provides 3 shots at 3+ to hit.
        Shot capacity is per incoming volley (handled by combat resolution).
        """
        pd_mounts = sum(1 for s in self.systems if s.is_active() and s.base == "D")
        if pd_mounts <= 0:
            return (0, 0)
        return (pd_mounts * 3, 3)

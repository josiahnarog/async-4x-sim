from __future__ import annotations

from typing import Tuple

from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable, Iterator
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

        Rules:
          - damage is applied point-by-point
          - ALWAYS skip systems that are already destroyed
          - weapon may skip specific codes (e.g. Laser skips 'S', Electron skips 'A' and 'H')
          - Electron Beam does half damage against shields, per point (rounded down)
            Implementation here: when the selected system is a shield, the point applies only
            if floor(1 * shield_multiplier) == 1; with 0.5 multiplier this means:
              - a single point would do 0 to shields (so effectively shields are very resistant)
            If you want "half total damage" instead, see note below.
        """
        if damage <= 0:
            return self

        systems = list(self.systems)  # assumes `self.systems` is a list[System] field
        skip = set(weapon.skip_codes)

        def is_destroyed(i: int) -> bool:
            return bool(systems[i].destroyed)

        def code_of(i: int) -> str:
            # only the leading capital letter is the "system code" for skip comparisons
            # (since you have camel-case modifiers like Xc)
            c = systems[i].code
            return c[:1] if c else ""

        def select_next_index() -> int | None:
            for i in range(len(systems)):
                if is_destroyed(i):
                    continue
                if code_of(i) in skip:
                    continue
                return i
            return None

        # Apply damage point-by-point to the next eligible system
        points = int(damage)
        while points > 0:
            idx = select_next_index()
            if idx is None:
                break

            code = code_of(idx)

            # Electron beam halves damage vs shields.
            # IMPORTANT: this interpretation matters. If you instead mean "halve TOTAL damage dealt
            # when the first impacted system is shields", we can change it. See note below.
            if code == "S" and weapon.shield_multiplier != 1.0:
                eff = int(1 * weapon.shield_multiplier)  # floor
                if eff <= 0:
                    # consumes the point but does not damage the shield
                    points -= 1
                    continue

            # Destroy this system box
            systems[idx] = replace(systems[idx], destroyed=True)
            points -= 1

        return type(self)(systems=systems)
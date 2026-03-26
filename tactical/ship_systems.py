from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Iterator

from tactical.weapons import WEAPONS, WeaponSpec, WeaponType
from tactical.ship_catalog import system_hull_spaces
from tactical.arcs import mount_type, MountType

_WEAPON_TYPE_BASES: frozenset[str] = frozenset(wt.value for wt in WeaponType)


# Default charges loaded into each system when parsed from compact notation.
# Weapon entries are derived from WeaponSpec.default_charges so they stay in
# sync when weapons are added or modified.  Non-weapon ammo-bearing systems
# (e.g. Mg) are listed here directly since they have no WeaponSpec.
_DEFAULT_CHARGES: dict[str, int] = {
    wt.value: spec.default_charges
    for wt, spec in WEAPONS.items()
    if spec.default_charges > 0
}
_DEFAULT_CHARGES["Mg"] = 50   # Magazine: 50 shared rounds (not a WeaponType)

# Maps weapon base code → magazine token that feeds it.
_WEAPON_MAGAZINE: dict[str, str] = {"R": "Mg"}


class SystemStatus(str, Enum):
    """Operational status of a single ship system.

    Status transitions are strictly one-way: INTACT → DESTROYED.
    There is no repair mechanic in tactical combat; a destroyed system
    stays destroyed for the duration of the encounter.

    Use System.destroy() to transition; direct attribute assignment will
    silently fail on the frozen dataclass.
    """
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

    # `base` is the single capital letter code (e.g. "B", "S", "R").
    # `token` (property) is the full display code: base + mods (e.g. "Bh", "Mg").
    base: str
    mods: str = ""
    status: SystemStatus = SystemStatus.INTACT
    group: int | None = None
    charges: int = 0        # shots remaining (non-zero only for ammo-bearing systems)
    occupant: str | None = None  # squadron ID docked here (Bh only)

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
            charges=self.charges,
            occupant=self.occupant,
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

    def __post_init__(self) -> None:
        if not self.systems:
            raise ValueError("ShipSystems cannot be empty")

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
            token = base + mods
            charges = _DEFAULT_CHARGES.get(token, _DEFAULT_CHARGES.get(base, 0))
            systems.append(System(base=base, mods=mods, group=group, charges=charges))
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

    def total_hull_spaces(self) -> int:
        """Total hull-spaces occupied by all systems (active and destroyed)."""
        return sum(system_hull_spaces(s.token) for s in self.systems)

    # ---------------------------------------------------------------------
    # Rendering / serialization
    # ---------------------------------------------------------------------

    def render_compact(self) -> str:
        """Render to compact notation.

        Destroyed systems are prefixed with '!' so lowercase
        letters remain available for system modifiers.

        Weapon systems are annotated with their mount type suffix:
          '^' — spinal mount (forward-only; weapon HS > half ship HS)
          '↔' — side mount  (lateral arcs;  weapon HS > one-third ship HS)
          (no suffix) — turret mount (all non-blind-spot arcs)
        """
        ship_hs = self.total_hull_spaces()

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

            token_str = f"!{b.token}" if b.status == SystemStatus.DESTROYED else b.token
            # Annotate ammo-bearing systems with remaining charges.
            if b.token in _DEFAULT_CHARGES or b.base in _DEFAULT_CHARGES:
                token_str += f"[{b.charges}]"
            # Annotate hangar bays with occupant (- when empty).
            elif b.token == "Bh":
                token_str += f"[{b.occupant if b.occupant is not None else '-'}]"
            # Annotate weapons with mount-type suffix (spinal/side only).
            if b.base in _WEAPON_TYPE_BASES:
                whs = system_hull_spaces(b.token)
                mt  = mount_type(whs, ship_hs)
                if mt == MountType.SPINAL:
                    token_str += "^"
                elif mt == MountType.SIDE:
                    token_str += "↔"
            out.append(token_str)

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
                    "charges": b.charges,
                    "occupant": b.occupant,
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
                    charges=int(b.get("charges", 0)),
                    occupant=b.get("occupant"),
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

    def _active_engine_count(self, engine_code: str = "I") -> int:
        """Count active engine systems, applying engine room rules.

        Engine room rule: a grouped cluster of engine systems contributes its
        full count only if every system in that group is intact. A single
        destroyed system in a room disables the entire room.

        Ungrouped engine systems (group=None) are counted individually.
        """
        count = 0

        # Ungrouped engines count individually.
        for s in self.systems:
            if s.base == engine_code and s.group is None and s.is_active():
                count += 1

        # Grouped systems: collect all systems per group, then apply room rule.
        groups: dict[int, list[System]] = {}
        for s in self.systems:
            if s.group is not None:
                groups.setdefault(s.group, []).append(s)

        for room in groups.values():
            if all(s.is_active() for s in room):
                count += sum(1 for s in room if s.base == engine_code)

        return count

    def movement_points(self, engine_code: str = "I", engine_power_ratio=None) -> int:
        """Return MP capacity from active engine systems.

        Applies engine room rules (see _active_engine_count). If
        engine_power_ratio is provided (a Fraction or float from a HullType),
        MP = floor(active_count * ratio). Otherwise defaults to 1:1.
        """
        from fractions import Fraction
        count = self._active_engine_count(engine_code)
        if engine_power_ratio is None:
            return count
        return int(count / Fraction(engine_power_ratio))

    # ---------------------------------------------------------------------
    # Mutation (pure, deterministic)
    # ---------------------------------------------------------------------

    def apply_damage(self, amount: int = 1) -> ShipSystems:
        """Apply `amount` points of raw damage left-to-right along the system track.

        Each point destroys the next intact system in track order.  Excess
        damage beyond the number of intact systems is silently absorbed (the
        ship is already fully destroyed).

        This is raw damage — no skip rules, no multipliers, no weapon-specific
        mechanics.  Use apply_weapon_damage() for all weapon fire; reserve this
        method for environmental or scripted damage that intentionally bypasses
        those rules.

        Track order is authoritative for sequencing and matches the rendering
        and display order.  Returns a new ShipSystems; does not mutate self.
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
        """Apply weapon damage to this ship's systems point-by-point.

        Skip rules (weapon.skip):
          The first skip.shields active S systems, skip.armor active A systems,
          and skip.holds active B systems are bypassed entirely — damage passes
          through them as if they don't exist.  Use SKIP_ALL to bypass all of
          a given type (e.g. Laser skips all shields).

        Damage multipliers:
          When the next eligible system is type S and shield_multiplier != 1.0,
          the remaining damage pool is multiplied (floor) before hitting that system
          and all subsequent ones.  Same for armor_multiplier vs type A.
        """
        if damage <= 0:
            return self

        systems = list(self.systems)
        skip = weapon.skip

        # Precompute which indices are pre-skipped for this weapon.
        # The first skip.shields active S systems are bypassed, etc.
        pre_skip: set[int] = set()
        seen: dict[str, int] = {}   # base → count of active instances processed so far
        _limits = {"S": skip.shields, "A": skip.armor, "B": skip.holds}
        for i, s in enumerate(systems):
            if not s.is_active():
                continue
            limit = _limits.get(s.base, 0)
            if limit == 0:
                continue
            n = seen.get(s.base, 0)
            if n < limit:
                pre_skip.add(i)
                seen[s.base] = n + 1

        def next_idx() -> int | None:
            for i in range(len(systems)):
                if systems[i].is_active() and i not in pre_skip:
                    return i
            return None

        points = int(damage)

        while points > 0:
            idx = next_idx()
            if idx is None:
                break

            if systems[idx].base == "S" and weapon.shield_multiplier != 1.0:
                points = int(points * weapon.shield_multiplier)
                if points <= 0:
                    break

            if systems[idx].base == "A" and weapon.armor_multiplier != 1.0:
                points = int(points * weapon.armor_multiplier)
                if points <= 0:
                    break

            systems[idx] = systems[idx].destroy()
            points -= 1

        return ShipSystems(tuple(systems))

    def destroy_system_at(self, idx: int) -> "ShipSystems":
        """Destroy the system at the given track index.  No-op if already destroyed."""
        if not (0 <= idx < len(self.systems)):
            return self
        s = self.systems[idx]
        if not s.is_active():
            return self
        systems = list(self.systems)
        systems[idx] = s.destroy()
        return ShipSystems(tuple(systems))

    def needle_beam_target(self, roll: int, skip: int = 30) -> int | None:
        """Compute the system index targeted by a needle beam penetration roll.

        Algorithm:
          1. Traverse the track counting S and A systems.  The first `skip` S/A
             systems form the 'pre-skip' zone; systems beyond that threshold — plus
             all non-S/A systems outside the pre-skip zone — form the eligible pool.
          2. Build the eligible pool: intact systems not in the pre-skip zone and
             not a bay (base == 'B').
          3. Select pool[((roll - 1) % len(pool))], wrapping when roll > pool size.
          4. Returns the system's index in self.systems, or None if pool is empty.

        Returns:
          int  — index into self.systems of the targeted system (always active).
          None — all eligible systems are already destroyed; the shot has no effect.

        'roll' is expected to be 1..10 (a d10 result).
        """
        # Mark the first `skip` S/A systems as pre-skip
        sa_count = 0
        pre_skip: set[int] = set()
        for i, s in enumerate(self.systems):
            if s.base in ("S", "A"):
                if sa_count < skip:
                    pre_skip.add(i)
                sa_count += 1

        # Build eligible pool: intact, non-bay, not pre-skip
        eligible: list[int] = [
            i for i, s in enumerate(self.systems)
            if i not in pre_skip and s.is_active() and s.base != "B"
        ]

        if not eligible:
            return None

        return eligible[(roll - 1) % len(eligible)]

    def is_destroyed(self) -> bool:
        """A ship is destroyed when all non-shield, non-armor systems are gone.

        S (shield) and A (armor) are passive defenses.  Once every weapon,
        engine, and utility system is destroyed the ship is a dead hulk.
        """
        _PASSIVE = {"S", "A"}
        return not any(
            s.is_active() and s.base not in _PASSIVE
            for s in self.systems
        )

    def hangar_bay_count(self) -> int:
        """Number of active Hangar Bay (Bh) systems.

        Each active Bh can store, refit, and refuel one squadron.
        """
        return sum(1 for s in self.systems if s.is_active() and s.token == "Bh")

    def launch_bay_count(self) -> int:
        """Number of active Launch Bay (Bl) systems.

        Each active Bl can launch or recover one squadron per turn.
        """
        return sum(1 for s in self.systems if s.is_active() and s.token == "Bl")

    def ammo_count_for(self, weapon_base: str) -> int:
        """Total available ammunition for a weapon: magazine charges + internal launcher charges.

        Only active systems are counted; a destroyed launcher or magazine contributes 0.
        """
        wb = weapon_base.upper()
        mag_token = _WEAPON_MAGAZINE.get(wb)
        total = 0
        for s in self.systems:
            if not s.is_active():
                continue
            if mag_token and s.token == mag_token:
                total += s.charges
            elif s.base == wb:
                total += s.charges
        return total

    def consume_ammo_for(self, weapon_base: str, count: int = 1) -> "ShipSystems":
        """Return new ShipSystems with `count` rounds consumed for `weapon_base`.

        Drains leftmost active magazine first, then leftmost active launcher.
        """
        if count <= 0:
            return self
        wb = weapon_base.upper()
        mag_token = _WEAPON_MAGAZINE.get(wb)
        systems = list(self.systems)
        remaining = count

        # Drain from magazines first (leftmost active Mg).
        if mag_token:
            for i, s in enumerate(systems):
                if remaining <= 0:
                    break
                if s.is_active() and s.token == mag_token and s.charges > 0:
                    drain = min(s.charges, remaining)
                    systems[i] = dataclasses.replace(s, charges=s.charges - drain)
                    remaining -= drain

        # Then drain from internal launcher charges — 1 shot per launcher,
        # so two launchers each lose 1 round rather than one losing 2.
        for i, s in enumerate(systems):
            if remaining <= 0:
                break
            if s.is_active() and s.base == wb and s.charges > 0:
                systems[i] = dataclasses.replace(s, charges=s.charges - 1)
                remaining -= 1

        return ShipSystems(tuple(systems))

    def dock_squadron(self, squadron_id: str) -> "ShipSystems":
        """Mark the first empty active Bh as occupied by squadron_id.

        Raises ValueError if no empty active hangar bay is available.
        """
        systems = list(self.systems)
        for i, s in enumerate(systems):
            if s.is_active() and s.token == "Bh" and s.occupant is None:
                systems[i] = dataclasses.replace(s, occupant=squadron_id)
                return ShipSystems(tuple(systems))
        raise ValueError(f"No empty active hangar bay available for {squadron_id!r}")

    def undock_squadron(self, squadron_id: str) -> "ShipSystems":
        """Clear the Bh that holds squadron_id.

        Raises ValueError if the squadron is not found in any hangar bay.
        """
        systems = list(self.systems)
        for i, s in enumerate(systems):
            if s.token == "Bh" and s.occupant == squadron_id:
                systems[i] = dataclasses.replace(s, occupant=None)
                return ShipSystems(tuple(systems))
        raise ValueError(f"Squadron {squadron_id!r} not found in any hangar bay")

    def shooting_mods(self) -> "ToHitMod":
        """Aggregate to-hit modifiers arising from ship condition.

        These are applied to every weapon fired by this ship.  Add new
        condition checks here; the results are summed automatically.

        Current conditions:
          - All Q (crew quarters / life support) destroyed:
              crew must fight in vacuum suits → −2 to all shooting (target_delta)
        """
        from tactical.attack_context import ToHitMod
        target_delta = 0

        q_systems = [s for s in self.systems if s.base == "Q"]
        if q_systems and not any(s.is_active() for s in q_systems):
            target_delta -= 2

        return ToHitMod(target_delta=target_delta)

    def point_defense(self) -> tuple[int, int]:
        """
        Returns (shots, to_hit) for point defense for the current incoming volley.

        Each intact 'D' system provides 3 shots at 3+ to hit.
        Shot capacity is per incoming volley (handled by combat resolution).
        """
        pd_mounts = sum(1 for s in self.systems if s.is_active() and s.base == "D")
        if pd_mounts <= 0:
            return (0, 0)
        return (pd_mounts * 3, 3)

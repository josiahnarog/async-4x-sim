from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Iterator


class BoxStatus(str, Enum):
    INTACT = "intact"
    DESTROYED = "destroyed"


@dataclass(frozen=True, slots=True)
class SystemBox:
    """A single damageable system 'box' on a ship's track.

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
    status: BoxStatus = BoxStatus.INTACT
    group: int | None = None

    def is_active(self) -> bool:
        return self.status == BoxStatus.INTACT

    def destroy(self) -> SystemBox:
        if self.status == BoxStatus.DESTROYED:
            return self
        return SystemBox(
            base=self.base,
            mods=self.mods,
            status=BoxStatus.DESTROYED,
            group=self.group,
        )

    @property
    def token(self) -> str:
        return f"{self.base}{self.mods}"


@dataclass(frozen=True, slots=True)
class SystemTrack:
    """Canonical representation of a ship's system track.

    Ordering of boxes is authoritative and used for:
      - deterministic damage application
      - rendering
      - capability queries
    """

    boxes: tuple[SystemBox, ...]

    # ---------------------------------------------------------------------
    # Parsing
    # ---------------------------------------------------------------------

    @staticmethod
    def parse(compact: str) -> SystemTrack:
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
        boxes: list[SystemBox] = []
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
            boxes.append(SystemBox(base=base, mods=mods, group=group))
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

        if not boxes:
            raise ValueError("SystemTrack cannot be empty")

        return SystemTrack(tuple(boxes))

    @staticmethod
    def from_boxes(boxes: Iterable[SystemBox]) -> SystemTrack:
        return SystemTrack(tuple(boxes))

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

        for b in self.boxes:
            if b.group != current_group:
                close_group()
                if b.group is not None:
                    out.append("(")
                    current_group = b.group

            out.append(f"!{b.token}" if b.status == BoxStatus.DESTROYED else b.token)

        close_group()
        return "".join(out)

    def to_dict(self) -> dict:
        return {
            "boxes": [
                {
                    "base": b.base,
                    "mods": b.mods,
                    "status": b.status.value,
                    "group": b.group,
                }
                for b in self.boxes
            ]
        }

    @staticmethod
    def from_dict(data: dict) -> SystemTrack:
        boxes: list[SystemBox] = []

        for b in data.get("boxes", []):
            status = BoxStatus(b.get("status", BoxStatus.INTACT.value))

            base = str(b["base"]).upper()
            if len(base) != 1 or not ("A" <= base <= "Z"):
                raise ValueError(f"Invalid base system code: {base!r}")

            mods = str(b.get("mods", ""))
            if any(not ("a" <= ch <= "z") for ch in mods):
                raise ValueError(f"Invalid system modifiers: {mods!r}")

            boxes.append(
                SystemBox(
                    base=base,
                    mods=mods,
                    status=status,
                    group=b.get("group"),
                )
            )

        return SystemTrack(tuple(boxes))

    # ---------------------------------------------------------------------
    # Queries
    # ---------------------------------------------------------------------

    def __iter__(self) -> Iterator[SystemBox]:
        return iter(self.boxes)

    def active_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for b in self.boxes:
            if b.is_active():
                counts[b.base] = counts.get(b.base, 0) + 1
        return counts

    def active_count(self, code: str) -> int:
        c = code.upper()
        return sum(1 for b in self.boxes if b.is_active() and b.base == c)

    def movement_points(self, engine_code: str = "I") -> int:
        """MVP rule: each intact engine box grants 1 movement point."""
        return self.active_count(engine_code)

    # ---------------------------------------------------------------------
    # Mutation (pure, deterministic)
    # ---------------------------------------------------------------------

    def apply_damage(self, amount: int = 1) -> SystemTrack:
        """Apply damage left-to-right to intact systems.

        Returns a new SystemTrack (does not mutate).
        """
        if amount <= 0:
            return self

        remaining = amount
        new_boxes: list[SystemBox] = []

        for b in self.boxes:
            if remaining > 0 and b.is_active():
                new_boxes.append(b.destroy())
                remaining -= 1
            else:
                new_boxes.append(b)

        return SystemTrack(tuple(new_boxes))

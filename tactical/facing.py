from __future__ import annotations

from enum import IntEnum


class Facing(IntEnum):
    """Hex facing direction (0..5) with a universal 'north'.

    We use axial (q, r). Direction vectors (dq, dr):
      N : ( 1,  0)
      NE: ( 1, -1)
      SE: ( 0, -1)
      S : (-1,  0)
      SW: (-1,  1)
      NW: ( 0,  1)

    These align with sim.hexgrid.Hex.neighbors() ordering (index 0..5).
    """

    # Canonical numeric directions
    D0 = 0
    D1 = 1
    D2 = 2
    D3 = 3
    D4 = 4
    D5 = 5

    # Readable aliases (universal "north" = 0)
    N = 0
    NE = 1
    SE = 2
    S = 3
    SW = 4
    NW = 5

    def left(self, steps: int = 1) -> "Facing":
        """Rotate left (counter-clockwise) by `steps`."""
        return Facing((int(self) - (steps % 6)) % 6)

    def right(self, steps: int = 1) -> "Facing":
        """Rotate right (clockwise) by `steps`."""
        return Facing((int(self) + (steps % 6)) % 6)

    @staticmethod
    def from_int(value: int) -> "Facing":
        """Explicit constructor for clarity at boundaries (serialization/UI)."""
        if value < 0 or value > 5:
            raise ValueError(f"Facing must be in 0..5, got {value}")
        return Facing(value)


FACING_OFFSETS: tuple[tuple[int, int], ...] = (
    (0, 1),    # N
    (1, 0),    # NE
    (1, -1),   # SE
    (0, -1),   # S
    (-1, 0),   # SW
    (-1, 1),   # NW
)


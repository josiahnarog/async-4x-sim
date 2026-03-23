from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FighterClass:
    designation: str  # e.g. "F1"
    name: str         # e.g. "Gen 1 Fighter"
    base_mvr: int     # base maneuverability before ordnance penalties
    base_mp: int      # base movement points before ordnance penalties


# ---------------------------------------------------------------------------
# Named fighter classes
# ---------------------------------------------------------------------------

F1 = FighterClass(
    designation="F1",
    name="Gen 1 Fighter",
    base_mvr=4,
    base_mp=10,
)

FIGHTER_CLASSES: dict[str, FighterClass] = {fc.designation: fc for fc in (F1,)}

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

from sim.hexgrid import Hex


@dataclass(frozen=True)
class RenderBounds:
    q_min: int
    q_max: int
    r_min: int
    r_max: int


def _owner_char(owner_name: str) -> str:
    # Display single-letter owner marker (A, B, C...)
    if not owner_name:
        return "?"
    return owner_name.strip()[0].upper()


def render_map_ascii(game, bounds: Optional[RenderBounds] = None) -> str:
    """
        Renders axial coords (q,r) as a simple offset grid:
          - Rows are r
          - Columns are q
          - Odd/even row indentation gives a hex-ish feel

        Cell content:
          - Your groups: group_id (e.g. G1)
          - Enemy groups: ?? (marker only)
          - Multiple groups in one hex: *
          - Empty: ..
        """
    groups = list(game.unit_groups.values())

    # Determine bounds around existing groups (or default bounds)
    if groups:
        qs = [g.location.q for g in groups]
        rs = [g.location.r for g in groups]
        min_q, max_q = min(qs) - 2, max(qs) + 2
        min_r, max_r = min(rs) - 2, max(rs) + 2
    else:
        min_q, max_q = -3, 3
        min_r, max_r = -3, 3

    # Build lookup: (q,r) -> list[groups]
    by_hex = {}
    for g in groups:
        by_hex.setdefault((g.location.q, g.location.r), []).append(g)

    print(f"Map bounds: q[{min_q}..{max_q}] r[{min_r}..{max_r}]")
    print("Legend: your group_id | enemy ?? | multiple * | empty ..\n")

    # Header row (q labels)
    header_cells = [f"{q:>2}" for q in range(min_q, max_q + 1)]
    print("      " + " ".join(header_cells))

    for r in range(min_r, max_r + 1):
        indent = "  " if (r - min_r) % 2 == 1 else ""
        row = [f"r={r:>2}  {indent}"]

        for q in range(min_q, max_q + 1):
            cell = ".."
            occupants = by_hex.get((q, r), [])

            if occupants:
                if len(occupants) >= 2:
                    cell = " *"
                else:
                    g = occupants[0]
                    if g.owner == game.active_player:
                        # show group id, truncated/padded to 2 chars
                        cell = f"{g.group_id[:2]:>2}"
                    else:
                        cell = "??"

            row.append(cell)

        print(" ".join(row))

    print("")  # trailing newline for REPL readability


from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from sim.hexgrid import Hex
from sim.units import PlayerID


@dataclass(frozen=True)
class RenderBounds:
    q_min: int
    q_max: int
    r_min: int
    r_max: int


def render_map_ascii(game, viewer, padding: int = 2) -> str:
    groups = list(game.unit_groups.values())
    if not groups:
        return "(no groups on map)"

    qs = [g.location.q for g in groups]
    rs = [g.location.r for g in groups]
    min_q, max_q = min(qs) - padding, max(qs) + padding
    min_r, max_r = min(rs) - padding, max(rs) + padding

    # Build occupancy lists
    by_hex = {}
    for g in groups:
        by_hex.setdefault((g.location.q, g.location.r), []).append(g)

    lines = []
    lines.append(f"Map view for Player {viewer} (Turn {game.turn_number})")
    lines.append("Legend: .. empty | G? your group | M# enemy marker | ** mixed/stack")
    lines.append("")

    header = "      " + " ".join(f"{q:>2}" for q in range(min_q, max_q + 1))
    lines.append(header)

    for r in range(min_r, max_r + 1):
        indent = "  " if (r - min_r) % 2 == 1 else ""
        row = [f"r={r:>2}  {indent}"]

        for q in range(min_q, max_q + 1):
            occ = by_hex.get((q, r), [])
            cell = ".."

            if occ:
                # Separate into friendly/enemy for this viewer
                friendly = [g for g in occ if g.owner == viewer]
                enemy = [g for g in occ if g.owner != viewer]

                if friendly and enemy:
                    cell = "**"  # contested / mixed (combat should usually prevent this)
                elif friendly:
                    # If multiple friendly groups stacked, show "G*"
                    cell = "G*" if len(friendly) > 1 else friendly[0].group_id[:2].rjust(2)
                else:
                    # Enemy only
                    if len(enemy) > 1:
                        cell = "M*"
                    else:
                        eg = enemy[0]
                        if game.is_revealed(viewer, eg.group_id):
                            cell = "R!"  # revealed enemy (placeholder)
                        else:
                            m = game.get_marker_id(viewer, eg.group_id)
                            cell = m[-2:].rjust(2)  # keep 2 chars; M1, M2, ...
            row.append(cell)

        lines.append(" ".join(row))

    return "\n".join(lines)

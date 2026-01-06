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


from sim.hexgrid import Hex

def render_map_ascii(game, viewer, padding: int = 2) -> str:
    groups = list(game.unit_groups.values())
    if not groups:
        return "(no groups on map)"

    if hasattr(game, "game_map") and game.game_map is not None:
        min_q, max_q = game.game_map.q_min, game.game_map.q_max
        min_r, max_r = game.game_map.r_min, game.game_map.r_max
    else:
        qs = [g.location.q for g in groups]
        rs = [g.location.r for g in groups]
        min_q, max_q = min(qs) - padding, max(qs) + padding
        min_r, max_r = min(rs) - padding, max(rs) + padding

    by_hex = {}
    for g in groups:
        by_hex.setdefault((g.location.q, g.location.r), []).append(g)

    lines = [
        f"Map view for Player {viewer} (Turn {game.turn_number})",
        "Legend: ?? unexplored empty | .. explored empty | ## blocked | G* friendly stack | M# enemy marker | R! revealed",
        ""
    ]

    header = "      " + " ".join(f"{q:>2}" for q in range(min_q, max_q + 1))
    lines.append(header)

    has_map = hasattr(game, "game_map") and game.game_map is not None
    has_explore = has_map and hasattr(game.game_map, "is_explored")

    for r in range(min_r, max_r + 1):
        indent = "  " if (r - min_r) % 2 == 1 else ""
        row = [f"r={r:>2}  {indent}"]

        for q in range(min_q, max_q + 1):
            h = Hex(q, r)
            occ = by_hex.get((q, r), [])

            # Out of bounds (only meaningful if we have a map)
            if has_map and not game.game_map.in_bounds(h):
                row.append("  ")
                continue

            # Blocked always visible
            if has_map and game.game_map.is_blocked(h):
                row.append("##")
                continue

            # Occupants render regardless of exploration
            if occ:
                row.append(render_occupants(game, viewer, occ))
                continue

            # Empty: show exploration fog (if supported), else normal empty
            if has_explore and not game.game_map.is_explored(h):
                row.append("??")
            else:
                row.append("..")

        lines.append(" ".join(row))

    return "\n".join(lines)


def render_occupants(game, viewer, occ) -> str:
    friendly = [g for g in occ if g.owner == viewer]
    enemy = [g for g in occ if g.owner != viewer]

    if friendly and enemy:
        return "**"
    if friendly:
        return "G*" if len(friendly) > 1 else friendly[0].group_id[:2].rjust(2)

    # Enemy only
    if len(enemy) > 1:
        return "M*"

    eg = enemy[0]
    if game.is_revealed(viewer, eg.group_id):
        return "R!"
    m = game.get_marker_id(viewer, eg.group_id)
    return m[-2:].rjust(2)

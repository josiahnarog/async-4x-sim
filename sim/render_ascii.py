from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from sim.hexgrid import Hex
from sim.units import PlayerID
from sim.map_content import HexContent

HEX_SYMBOLS = {
    HexContent.HOMEWORLD: "HW",
    HexContent.PLANET_STANDARD: "P ",
    HexContent.PLANET_BARREN: "Pb",
    HexContent.SUPERNOVA: "SN",
    HexContent.MINERALS: "Mn",
    HexContent.HORROR: "Hr",
    HexContent.CLEAR: "..",
}
def render_hex_content_symbol(game, h: "Hex") -> str:
    """
    Returns a 2-char symbol for the hex's explored content.
    Falls back to '..' if content system not present.
    """
    if not hasattr(game, "game_map") or game.game_map is None:
        return ".."
    gm = game.game_map
    if not hasattr(gm, "get_hex_content"):
        return ".."
    content = gm.get_hex_content(h)
    return HEX_SYMBOLS.get(content, "..")


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
        "Legend: ?? unexplored | .. clear | ## blocked | HW homeworld | P  planet | Pb barren | SN supernova | Mn "
        "minerals | Hr horror | G* friendly | M# enemy | R! revealed",
        ""
    ]

    header = "      " + " ".join(f"{q:>2}" for q in range(min_q, max_q + 1))
    lines.append(header)

    has_map = hasattr(game, "game_map") and game.game_map is not None
    has_explore = has_map and hasattr(game.game_map, "is_explored")

    for r in range(max_r, min_r - 1, -1):
        indent = "  " if (r % 2) != 0 else ""
        row = [f"r={r:>2}  {indent}"]

        for q in range(min_q, max_q + 1):
            h = Hex(q, r)
            occ = by_hex.get((q, r), [])

            if has_map and not game.game_map.in_bounds(h):
                row.append("  ")
                continue

            if has_map and game.game_map.is_blocked(h):
                row.append("##")
                continue

            if occ:
                row.append(render_occupants(game, viewer, occ))
                continue

            # Empty: show exploration fog (if supported). If explored, show terrain symbol.
            if has_explore and not game.game_map.is_explored(h):
                row.append("??")
            else:
                row.append(render_hex_content_symbol(game, h) if has_map else "..")

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

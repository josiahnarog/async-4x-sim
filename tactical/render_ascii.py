from __future__ import annotations

from sim.hexgrid import Hex
from tactical.battle_state import BattleState
from tactical.facing import Facing


def axial_distance(a: Hex, b: Hex) -> int:
    """Hex distance in axial coords."""
    dq = abs(a.q - b.q)
    dr = abs(a.r - b.r)
    ds = abs((a.q + a.r) - (b.q + b.r))
    return max(dq, dr, ds)


def ship_cell_symbol(ship_id: str, owner_id: str, facing: Facing) -> str:
    """2-char symbol: owner initial + facing glyph (caret-style)."""
    owner = (owner_id.strip() or "?")[:1].upper()
    return owner + facing_glyph(facing)


def render_tactical_grid_ascii(
    battle: BattleState,
    *,
    radius: int = 4,
    center: Hex = Hex(0, 0),
    empty: str = "..",
) -> str:
    """Render a coordinate-labeled tactical hex grid (2-char cells), fixed-width.

    This matches the Strategic REPL feel:
      - fixed q columns for every row (aligned under header)
      - alternating indent only (no row shortening)
      - no blank/outside cells; everything inside the printed rectangle is shown
    """
    if radius < 0:
        raise ValueError("radius must be >= 0")
    if len(empty) != 2:
        raise ValueError("empty must be exactly 2 characters")

    ship_at = {s.pos: s for s in battle.ships.values()}

    q_min = center.q - radius
    q_max = center.q + radius
    r_min = center.r - radius
    r_max = center.r + radius

    lines: list[str] = []

    # Header aligned to the columns below: 6 spaces then each q as width 3
    header_nums = [f"{q:>3}" for q in range(q_min, q_max + 1)]
    lines.append("      " + "".join(header_nums))

    # Rows: from high r down to low r
    for r in range(r_max, r_min - 1, -1):
        indent = "  " if ((r - center.r) % 2 != 0) else ""
        row = [f"r={r:>2} " + indent]

        for q in range(q_min, q_max + 1):
            h = Hex(q, r)
            ship = ship_at.get(h)
            sym = ship_cell_symbol(ship.ship_id, ship.owner_id, ship.facing) if ship else empty
            row.append(f" {sym}")

        lines.append("".join(row))

    return "\n".join(lines)


def facing_glyph(facing: Facing) -> str:
    return {
        Facing.N: "↑",
        Facing.NE: "↗",
        Facing.SE: "↘",
        Facing.S: "↓",
        Facing.SW: "↙",
        Facing.NW: "↖",
    }[Facing(int(facing))]


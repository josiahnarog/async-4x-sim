"""Campaign web routes.

Endpoints:
    GET  /campaign/             → galaxy overview (force-layout graph)
    GET  /campaign/new          → regenerate galaxy, redirect to /campaign/
    GET  /campaign/system/{id}  → system detail (polar sH map)
    GET  /campaign/api/galaxy   → JSON galaxy data for JS renderer
"""

from __future__ import annotations

import json
import math
import random
from typing import Optional

from fastapi import APIRouter
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from campaign.generator import (
    HUMAN_HOME_SPEC,
    SystemSpec,
    build_system_from_spec,
    generate_system_with_companions,
)
from campaign.linker import build_galaxy
from campaign.models import (
    AnomalyType,
    CampaignShip,
    Galaxy,
    LM_PER_SH,
    LM_PER_SPEED_PER_DAY,
    MoveLeg,
    MoonType,
    Planet,
    PlanetType,
    Population,
    SpectralClass,
    Star,
    SystemNode,
    TransitLeg,
    WPVisibility,
)
from campaign.hex_utils import axial_to_screen, cube_round, hex_dist
from campaign.routing import build_route, ship_system_and_pos_at
from campaign.tables import classify_orbit, get_zone_bounds

router = APIRouter(prefix="/campaign")
templates = Jinja2Templates(directory="templates")

# ---------------------------------------------------------------------------
# In-memory galaxy store
# ---------------------------------------------------------------------------

_galaxy: Optional[Galaxy] = None
_galaxy_seed: int = 42


_DEFAULT_SYSTEM_OVERRIDES: dict[str, SystemSpec] = {
    "SYS-0001": HUMAN_HOME_SPEC,
}


def _make_galaxy(
    seed: int,
    n_systems: int = 24,
    system_overrides: dict[str, SystemSpec] | None = None,
) -> Galaxy:
    if system_overrides is None:
        system_overrides = _DEFAULT_SYSTEM_OVERRIDES
    rng = random.Random(seed)
    systems: dict[str, SystemNode] = {}
    for i in range(n_systems):
        node_id = f"SYS-{i + 1:04d}"
        spec = system_overrides.get(node_id)
        if spec is not None:
            node = build_system_from_spec(rng, node_id, spec)
        else:
            r = rng.random()
            add_bin = r < 0.30
            add_tri = add_bin and rng.random() < 0.15
            node = generate_system_with_companions(
                rng, node_id, add_binary=add_bin, add_trinary=add_tri
            )
        systems[node_id] = node
    g = build_galaxy(systems, rng)
    # Spawn the U.N.S. Broadside (DD, speed 5) in the first system
    first_id = next(iter(g.systems))
    g.systems[first_id].ships.append(CampaignShip(
        ship_id="broadside-1",
        name="U.N.S. Broadside",
        hull_type="DD",
        speed=5,
        system_id=first_id,
        q_sh=0, r_sh=0,
    ))
    return g


def _get_galaxy() -> Galaxy:
    global _galaxy
    if _galaxy is None:
        _galaxy = _make_galaxy(_galaxy_seed)
    return _galaxy


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

_SPECTRAL_COLOURS: dict[str, str] = {
    SpectralClass.WHITE.value:        "#ffffff",
    SpectralClass.YELLOW_WHITE.value: "#ffffaa",
    SpectralClass.YELLOW.value:       "#ffff44",
    SpectralClass.ORANGE.value:       "#ff9900",
    SpectralClass.RED.value:          "#ff4422",
    SpectralClass.RED_DWARF.value:    "#cc1100",
    SpectralClass.BLUE_GIANT.value:   "#4488ff",
    SpectralClass.WHITE_DWARF.value:  "#ddeeff",
    SpectralClass.RED_GIANT.value:    "#ff6600",
}

_PLANET_COLOURS: dict[str, str] = {
    PlanetType.T.value:   "#44bb44",
    PlanetType.ST.value:  "#338833",
    PlanetType.B.value:   "#888888",
    PlanetType.H.value:   "#ff5500",
    PlanetType.V.value:   "#ffaa00",
    PlanetType.F.value:   "#aaccff",
    PlanetType.G.value:   "#ddaa44",
    PlanetType.I.value:   "#88aacc",
    PlanetType.AST.value: "#555555",
}

_WP_VIS_COLOURS: dict[str, str] = {
    WPVisibility.OPEN.value:   "#44ddff",
    WPVisibility.CLOSED.value: "#ff4444",
}


def _node_star_colour(node: SystemNode) -> str:
    p = node.primary
    if p is None:
        return "#555555"
    if p.anomaly_type is not None:
        return "#aa44ff"
    if p.spectral_class is not None:
        return _SPECTRAL_COLOURS.get(p.spectral_class.value, "#888888")
    return "#888888"


def _node_label(node: SystemNode) -> str:
    p = node.primary
    if p is None:
        return "Starless"
    if p.anomaly_type is not None:
        return p.anomaly_type.value
    if p.spectral_class is not None:
        return p.spectral_class.value
    return "?"


# ---------------------------------------------------------------------------
# Galaxy JSON API (consumed by JS force layout)
# ---------------------------------------------------------------------------

@router.get("/api/galaxy", response_class=JSONResponse)
async def api_galaxy():
    g = _get_galaxy()
    node_index = {sid: i for i, sid in enumerate(g.systems)}

    nodes = []
    for sid, node in g.systems.items():
        total_planets = sum(len(s.planets) for s in node.stars)
        nodes.append({
            "id":       sid,
            "label":    sid,
            "colour":   _node_star_colour(node),
            "type":     _node_label(node),
            "planets":  total_planets,
            "wps":      len(node.warp_points),
            "stars":    len(node.stars),
            "ships":    len(node.ships),
        })

    edges = []
    for e in g.edges:
        edges.append({
            "a":     node_index[e.system_a],
            "b":     node_index[e.system_b],
            "wp_a":  e.wp_a,
            "wp_b":  e.wp_b,
        })

    ships = []
    for node in g.systems.values():
        for s in node.ships:
            ships.append({
                "ship_id":   s.ship_id,
                "name":      s.name,
                "hull_type": s.hull_type,
                "system_id": s.system_id,
                "legs":      _serialize_legs(s.route),
            })

    return {"nodes": nodes, "edges": edges, "ships": ships}


# ---------------------------------------------------------------------------
# Hex grid SVG helpers for system view  (1 hex = 1 sH, flat-top)
# ---------------------------------------------------------------------------

_HEX_SIZE  = 9     # pixels: centre-to-corner (= 1 sH in display)
_DISPLAY_R = 50    # sH radius of hex disk to render (50 LM ≈ 6 AU inner-system background)

_SVG_W  = 1000
_SVG_H  = 1150
_SVG_CX = 500
_SVG_CY = 575

_ZONE_COLOURS: dict[str, str] = {
    "hot":        "#2a1208",
    "lwz":        "#0f2010",
    "cold_rocky": "#0c1218",
    "gas":        "#0a1020",
    "ice":        "#080e22",
    "beyond":     "#060812",
}


def _axial_to_pixel(q: int | float, r: int | float) -> tuple[float, float]:
    """Flat-top hex axial coords → pixel offset from grid centre."""
    sx, sy = axial_to_screen(q, r)
    return _HEX_SIZE * sx, _HEX_SIZE * sy


def _hex_poly(cx: float, cy: float) -> str:
    """SVG polygon points string for flat-top hex centred at (cx, cy)."""
    pts = []
    for i in range(6):
        a = math.radians(60 * i)
        pts.append(f"{cx + _HEX_SIZE * math.cos(a):.1f},{cy + _HEX_SIZE * math.sin(a):.1f}")
    return " ".join(pts)


_SQ3 = math.sqrt(3)


def _zone_bands(sc: SpectralClass | None, display_r: int) -> list[tuple[float, str]]:
    """Return list of (outer_radius_px, colour) from outermost to innermost.

    Used to paint circular zone rings via painter's algorithm.
    """
    # Always start with a full background circle
    display_px = _HEX_SIZE * _SQ3 * display_r

    if sc is None:
        return [(display_px, _ZONE_COLOURS["beyond"])]

    bounds = get_zone_bounds(sc)
    if bounds is None:
        return [(display_px, _ZONE_COLOURS["beyond"])]

    tl_lo, tl_hi = bounds["tidelock"]
    rk_lo, rk_hi = bounds["rocky"]
    gs_lo, gs_hi = bounds["gas"]
    ic_lo, ic_hi = bounds["ice"]
    bio = bounds["biosphere"]

    # Collect all meaningful zone boundaries within display_r, sorted ascending
    breakpoints = sorted(set(
        v for v in [
            0, rk_lo, tl_hi, rk_hi,
            bio[0] if bio else None, bio[1] if bio else None,
            gs_lo, gs_hi, ic_lo, ic_hi, display_r,
        ]
        if v is not None and v <= display_r
    ))
    if not breakpoints or breakpoints[-1] < display_r:
        breakpoints.append(display_r)

    # Build (inner, outer, zone) bands, then reverse for painter's algorithm
    bands: list[tuple[float, str]] = []
    for i in range(len(breakpoints) - 1):
        inner_sh = breakpoints[i]
        outer_sh = breakpoints[i + 1]
        mid_sh = (inner_sh + outer_sh) / 2
        if mid_sh <= 0:
            zone = "beyond"
        else:
            zone = classify_orbit(sc, round(mid_sh))
        outer_px = _HEX_SIZE * _SQ3 * outer_sh
        bands.append((outer_px, _ZONE_COLOURS.get(zone, _ZONE_COLOURS["beyond"])))

    # Painter's algorithm: draw outermost band first
    return list(reversed(bands))


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _render_system_svg(node: SystemNode) -> str:
    parts: list[str] = []

    primary = node.primary
    sc = primary.spectral_class if (primary and primary.anomaly_type is None) else None

    # Background
    parts.append(f'<rect width="{_SVG_W}" height="{_SVG_H}" fill="#060612"/>')

    # --- Circular zone bands (painter's algorithm: outermost first) ---
    for outer_px, col in _zone_bands(sc, _DISPLAY_R):
        parts.append(
            f'<circle cx="{_SVG_CX}" cy="{_SVG_CY}" r="{outer_px:.1f}" fill="{col}"/>'
        )

    # --- Hex grid overlay (outline only, no fill) ---
    for q in range(-_DISPLAY_R, _DISPLAY_R + 1):
        for r in range(-_DISPLAY_R, _DISPLAY_R + 1):
            if hex_dist(q, r) > _DISPLAY_R:
                continue
            dx, dy = _axial_to_pixel(q, r)
            cx, cy = _SVG_CX + dx, _SVG_CY + dy
            pts = _hex_poly(cx, cy)
            parts.append(
                f'<polygon points="{pts}" fill="none" stroke="#111128" stroke-width="0.4"/>'
            )

    # --- WP dashed lines from centre (use stored canonical coords) ---
    for wp in node.warp_points:
        dx, dy = _axial_to_pixel(wp.q_sh, wp.r_sh)
        col = _WP_VIS_COLOURS.get(wp.visibility.value, "#44ddff")
        parts.append(
            f'<line x1="{_SVG_CX}" y1="{_SVG_CY}" '
            f'x2="{_SVG_CX + dx:.1f}" y2="{_SVG_CY + dy:.1f}" '
            f'stroke="{col}" stroke-width="0.8" stroke-dasharray="4,3" opacity="0.5"/>'
        )

    # Scale note
    parts.append(
        f'<text x="8" y="{_SVG_H - 8}" fill="#223344" font-size="8" '
        f'font-family="monospace">1 hex = 1 sH</text>'
    )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Route serialization helper
# ---------------------------------------------------------------------------

def _serialize_legs(route: list) -> list[dict]:
    out: list[dict] = []
    for leg in route:
        if isinstance(leg, MoveLeg):
            out.append({
                "type": "move",
                "system_id": leg.system_id,
                "from_q": leg.from_q, "from_r": leg.from_r,
                "to_q":   leg.to_q,   "to_r":   leg.to_r,
                "start_day":  leg.start_day,
                "arrive_day": leg.arrive_day,
            })
        elif isinstance(leg, TransitLeg):
            out.append({
                "type": "transit",
                "from_system": leg.from_system,
                "to_system":   leg.to_system,
                "day":         leg.day,
                "exit_q":      leg.exit_q,
                "exit_r":      leg.exit_r,
            })
    return out


# ---------------------------------------------------------------------------
# Orbital data builder (consumed by JS time scrubber)
# ---------------------------------------------------------------------------

def _build_orbital_data(node: SystemNode, galaxy: Galaxy) -> dict:
    """Return a JSON-serialisable dict of orbital parameters for all moving objects."""
    stars_out = []
    for star in node.stars:
        if star.anomaly_type is not None:
            col = "#aa44ff"
            lbl = star.anomaly_type.value[:3].upper()
        elif star.spectral_class is not None:
            col = _SPECTRAL_COLOURS.get(star.spectral_class.value, "#ffffff")
            lbl = star.component
        else:
            col = "#888888"
            lbl = star.component

        planets_out = []
        for p in star.planets:
            col_p = _PLANET_COLOURS.get(p.planet_type.value, "#888888")
            pr = 3
            if p.planet_type != PlanetType.AST:
                pr = 6 if p.mass == 3 else (5 if p.mass == 2 else 4)

            label_p = p.planet_type.value
            if p.hi is not None:
                label_p += f" HI{p.hi}"

            moons_out = []
            for m in p.moons:
                moons_out.append({
                    "orbit_th":            m.orbit_th,
                    "orbital_angle_0":     m.orbital_angle_0,
                    "orbital_period_days": m.orbital_period_days,
                    "is_big":              m.is_big,
                })

            pop_out = None
            if p.population is not None:
                pop_out = {
                    "owner":    p.population.owner,
                    "size":     p.population.size,
                    "industry": p.population.industry,
                }

            planets_out.append({
                "distance_sh":          p.distance_sh,
                "orbital_angle_0":      p.orbital_angle_0,
                "orbital_period_years": p.orbital_period_years,
                "planet_type":          p.planet_type.value,
                "colour":               col_p,
                "label":                label_p,
                "radius_px":            pr,
                "is_ast":               p.planet_type == PlanetType.AST,
                "moons":                moons_out,
                "population":           pop_out,
            })

        stars_out.append({
            "component":             star.component,
            "distance_sh":           star.distance_sh,
            "orbital_angle_0":       star.orbital_angle_0,
            "orbital_period_years":  star.orbital_period_years,
            "colour":                col,
            "label":                 lbl,
            "radius_px":             20 if star.component == "A" else 14,
            "planets":               planets_out,
        })

    wps_out = []
    for wp in node.warp_points:
        dx, dy = _axial_to_pixel(wp.q_sh, wp.r_sh)
        col = _WP_VIS_COLOURS.get(wp.visibility.value, "#44ddff")
        dest = wp.linked_to[0] if wp.linked_to else "?"
        wps_out.append({
            "x":     _SVG_CX + dx,
            "y":     _SVG_CY + dy,
            "colour": col,
            "label":  f"\u2192{dest}",
        })

    # Include ALL ships from the galaxy so JS can filter by computed system at tDays.
    ships_out = []
    for sys_node in galaxy.systems.values():
        for ship in sys_node.ships:
            # Pre-computed pixel move_legs for this system's ghost path rendering
            move_legs = []
            for leg in ship.route:
                if isinstance(leg, MoveLeg) and leg.system_id == node.node_id:
                    fx, fy = _axial_to_pixel(leg.from_q, leg.from_r)
                    tx, ty = _axial_to_pixel(leg.to_q,   leg.to_r)
                    move_legs.append({
                        "from_x":    _SVG_CX + fx,
                        "from_y":    _SVG_CY + fy,
                        "to_x":      _SVG_CX + tx,
                        "to_y":      _SVG_CY + ty,
                        "from_q":    leg.from_q,
                        "from_r":    leg.from_r,
                        "to_q":      leg.to_q,
                        "to_r":      leg.to_r,
                        "start_day": leg.start_day,
                        "arrive_day": leg.arrive_day,
                    })
            ships_out.append({
                "ship_id":    ship.ship_id,
                "name":       ship.name,
                "hull_type":  ship.hull_type,
                "sH_per_day": ship.sH_per_day,
                "system_id":  ship.system_id,
                "q_sh":       ship.q_sh,
                "r_sh":       ship.r_sh,
                "order_day":  ship.order_day,
                "legs":       _serialize_legs(ship.route),
                "move_legs":  move_legs,
            })

    return {
        "hex_size":    _HEX_SIZE,
        "svg_cx":      _SVG_CX,
        "svg_cy":      _SVG_CY,
        "node_id":     node.node_id,
        "stars":       stars_out,
        "warp_points": wps_out,
        "ships":       ships_out,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def galaxy_view(request: Request):
    _get_galaxy()  # ensure generated
    return templates.TemplateResponse(
        "campaign_galaxy.html",
        {"request": request, "seed": _galaxy_seed},
    )


@router.get("/new", response_class=HTMLResponse)
async def new_galaxy(request: Request, seed: int = 0):
    global _galaxy, _galaxy_seed
    import time
    _galaxy_seed = seed if seed else int(time.time()) % 100_000
    _galaxy = _make_galaxy(_galaxy_seed)
    return RedirectResponse(url="/campaign/")


@router.get("/system/{node_id}", response_class=HTMLResponse)
async def system_view(request: Request, node_id: str):
    g = _get_galaxy()
    node = g.systems.get(node_id)
    if node is None:
        return HTMLResponse(f"<h1>System {node_id} not found</h1>", status_code=404)

    svg_content = _render_system_svg(node)

    # Build summary data for the side panel
    primary = node.primary
    star_info = []
    for star in node.stars:
        if star.anomaly_type:
            label = f"{star.component}: {star.anomaly_type.value}"
        elif star.spectral_class:
            label = f"{star.component}: {star.spectral_class.value}"
        else:
            label = f"{star.component}: unknown"
        if star.bearing:
            label += f"  bearing={star.bearing}  dist={star.distance_sh}sH"
        star_info.append(label)

    planet_info = []
    seen_ast_rings: set[tuple[str, int, int]] = set()   # (component, orbit_slot, distance_sh)
    for star in node.stars:
        for p in star.planets:
            if p.planet_type == PlanetType.AST:
                key = (star.component, p.orbit_slot, p.distance_sh)
                if key in seen_ast_rings:
                    continue
                seen_ast_rings.add(key)
                belt_size = 6 * p.distance_sh
                planet_info.append(
                    f"Orbit {p.orbit_slot:2d} @ {p.distance_sh:4d}sH  "
                    f"AST belt  ({belt_size} hexes)  [{star.component}]"
                )
            else:
                hi_str = f" HI={p.hi}" if p.hi is not None else ""
                tl_str = " [tidelock]" if p.tidelock else ""
                atm_str = " [atm]" if p.has_atmosphere else ""
                moon_str = f" {len(p.moons)}☽" if p.moons else ""
                pop_str = ""
                if p.population is not None:
                    pop_str = f" ◉ {p.population.owner} P{p.population.size}/I{p.population.industry}"
                planet_info.append(
                    f"Orbit {p.orbit_slot:2d} @ {p.distance_sh:4d}sH  "
                    f"{p.planet_type.value:3s}  M{p.mass or '-'}"
                    f"{hi_str}{tl_str}{atm_str}{moon_str}{pop_str}  [{star.component}]"
                )

    wp_info = []
    for wp in node.warp_points:
        dest = wp.linked_to[0] if wp.linked_to else "unlinked"
        wp_info.append(
            f"{wp.wp_id}  bearing={wp.bearing:2d}  dist={wp.distance_sh:3d}sH  "
            f"{wp.visibility.value:10s}  → {dest}"
        )

    orbital_json = json.dumps(_build_orbital_data(node, g))

    return templates.TemplateResponse(
        "campaign_system.html",
        {
            "request":      request,
            "node_id":      node_id,
            "svg":          svg_content,
            "star_info":    star_info,
            "planet_info":  planet_info,
            "wp_info":      wp_info,
            "svg_w":        _SVG_W,
            "svg_h":        _SVG_H,
            "orbital_json": orbital_json,
        },
    )


@router.post("/system/{node_id}/ship/{ship_id}/move", response_class=JSONResponse)
async def ship_move(node_id: str, ship_id: str,
                    dest_q: int, dest_r: int, t_days: float) -> JSONResponse:
    """Issue an intra-system movement order.

    Advances the ship to t_days, then replaces its route with a single
    MoveLeg to (dest_q, dest_r) within this system.  Returns updated
    orbital JSON.  (Extension point: calling this from the system view
    after routing to a WP enables manual intra-system waypointing.)
    """
    g = _get_galaxy()
    node = g.systems.get(node_id)
    if node is None:
        return JSONResponse({"error": "system not found"}, status_code=404)

    ship = next((s for s in node.ships if s.ship_id == ship_id), None)
    if ship is None:
        return JSONResponse({"error": "ship not found"}, status_code=404)

    _, cur_q, cur_r = ship_system_and_pos_at(ship, t_days)
    dist = hex_dist(cur_q, cur_r, dest_q, dest_r)
    arrive_day = t_days + dist / ship.sH_per_day if ship.sH_per_day > 0 else t_days

    new_route = []
    if dist > 0:
        new_route = [MoveLeg(
            system_id=node_id,
            from_q=cur_q, from_r=cur_r,
            to_q=dest_q, to_r=dest_r,
            start_day=t_days,
            arrive_day=arrive_day,
        )]

    idx = node.ships.index(ship)
    node.ships[idx] = CampaignShip(
        ship_id=ship.ship_id, name=ship.name,
        hull_type=ship.hull_type, speed=ship.speed,
        system_id=node_id, q_sh=cur_q, r_sh=cur_r,
        order_day=t_days, route=new_route,
    )
    return JSONResponse(_build_orbital_data(node, g))


@router.post("/ship/{ship_id}/route", response_class=JSONResponse)
async def ship_route(ship_id: str, dest_system_id: str, t_days: float) -> JSONResponse:
    """Issue an interstellar route order from the galaxy view.

    BFS-plans a full warp-point path and replaces the ship's route with
    the computed leg list.  The ship's snapshot position and system_id are
    advanced to t_days before planning.
    """
    g = _get_galaxy()

    ship = None
    ship_node = None
    for node in g.systems.values():
        found = next((s for s in node.ships if s.ship_id == ship_id), None)
        if found:
            ship = found
            ship_node = node
            break

    if ship is None:
        return JSONResponse({"error": "ship not found"}, status_code=404)
    if dest_system_id not in g.systems:
        return JSONResponse({"error": "destination system not found"}, status_code=404)

    new_legs = build_route(g, ship, dest_system_id, t_days)

    # Advance snapshot to t_days and attach new route
    cur_sys, cur_q, cur_r = ship_system_and_pos_at(ship, t_days)
    idx = ship_node.ships.index(ship)
    ship_node.ships[idx] = CampaignShip(
        ship_id=ship.ship_id, name=ship.name,
        hull_type=ship.hull_type, speed=ship.speed,
        system_id=cur_sys, q_sh=cur_q, r_sh=cur_r,
        order_day=t_days, route=new_legs,
    )

    # If the ship moved to a different system in the snapshot, update lists
    if cur_sys != ship_node.node_id:
        ship_node.ships.pop(idx)
        g.systems[cur_sys].ships.append(ship_node.ships[idx] if idx < len(ship_node.ships) else CampaignShip(
            ship_id=ship.ship_id, name=ship.name,
            hull_type=ship.hull_type, speed=ship.speed,
            system_id=cur_sys, q_sh=cur_q, r_sh=cur_r,
            order_day=t_days, route=new_legs,
        ))

    hops = sum(1 for leg in new_legs if isinstance(leg, TransitLeg))
    return JSONResponse({"ok": True, "hops": hops, "legs": len(new_legs)})

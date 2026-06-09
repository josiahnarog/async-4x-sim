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
    Engagement,
    EngagementStatus,
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
from campaign.combat_bridge import auto_resolve_stub, build_battle_from_engagement
from campaign.routing import find_path_collision
from ships.catalogue import BROADSIDE_CLASS, RAIDER_CLASS
from ships.instance import ShipInstance
from campaign.hex_utils import axial_to_screen, cube_round, hex_dist
from campaign.routing import build_intercept_route, build_route, ship_system_and_pos_at
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
    # Spawn starting ships in the first system
    first_id = next(iter(g.systems))
    g.systems[first_id].ships.append(CampaignShip(
        ship_id="broadside-1",
        name="U.N.S. Broadside",
        instance=ShipInstance.from_design(BROADSIDE_CLASS, "broadside-1"),
        system_id=first_id,
        q_sh=0, r_sh=0,
        owner="human",
    ))
    g.systems[first_id].ships.append(CampaignShip(
        ship_id="raider-1",
        name="R.S.S. Raider",
        instance=ShipInstance.from_design(RAIDER_CLASS, "raider-1"),
        system_id=first_id,
        q_sh=-8, r_sh=5,
        owner="npc_1",
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
                "hull_type": s.instance.design.hull_type_id,
                "owner":     s.owner,
                "system_id": s.system_id,
                "legs":      _serialize_legs(s.route),
            })

    return {"nodes": nodes, "edges": edges, "ships": ships, "game_time": g.game_time}


@router.get("/api/system/{node_id}", response_class=JSONResponse)
async def api_system(node_id: str):
    """Return current orbital data for a system (same payload as the HTML template)."""
    g = _get_galaxy()
    node = g.systems.get(node_id)
    if node is None:
        return JSONResponse({"error": "system not found"}, status_code=404)
    return JSONResponse(_build_orbital_data(node, g))


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
                "ship_id":          ship.ship_id,
                "name":             ship.name,
                "hull_type":        ship.instance.design.hull_type_id,
                "design_name":      ship.instance.design.name,
                "systems":          ship.instance.systems.render_compact(),
                "owner":            ship.owner,
                "sH_per_day":       ship.sH_per_day,
                "system_id":        ship.system_id,
                "q_sh":             ship.q_sh,
                "r_sh":             ship.r_sh,
                "order_day":        ship.order_day,
                "intercept_target": ship.intercept_target,
                "legs":             _serialize_legs(ship.route),
                "move_legs":        move_legs,
            })

    engagements_out = []
    for eng in galaxy.engagements:
        if eng.status == EngagementStatus.RESOLVED:
            continue
        if eng.system_id != node.node_id:
            continue
        dx, dy = _axial_to_pixel(eng.q_sh, eng.r_sh)
        engagements_out.append({
            **_eng_to_dict(eng),
            "x": _SVG_CX + dx,
            "y": _SVG_CY + dy,
        })

    return {
        "hex_size":    _HEX_SIZE,
        "svg_cx":      _SVG_CX,
        "svg_cy":      _SVG_CY,
        "node_id":     node.node_id,
        "game_time":   galaxy.game_time,
        "stars":       stars_out,
        "warp_points": wps_out,
        "ships":       ships_out,
        "engagements": engagements_out,
    }


# ---------------------------------------------------------------------------
# Engagement helpers
# ---------------------------------------------------------------------------

def _eng_to_dict(e: Engagement) -> dict:
    return {
        "engagement_id":    e.engagement_id,
        "system_id":        e.system_id,
        "q_sh":             e.q_sh,
        "r_sh":             e.r_sh,
        "ship_ids":         e.ship_ids,
        "status":           e.status.value,
        "collision_day":    e.collision_day,
        "tactical_game_id": e.tactical_game_id,
    }


# ---------------------------------------------------------------------------
# Intercept recalculation
# ---------------------------------------------------------------------------

def _recalc_intercepts(galaxy: Galaxy, moved_ship: CampaignShip, t_days: float) -> None:
    """Recompute routes for all ships currently holding an intercept order on moved_ship."""
    for sys_node in galaxy.systems.values():
        for i, s in enumerate(sys_node.ships):
            if s.intercept_target != moved_ship.ship_id:
                continue
            new_route = build_intercept_route(galaxy, s, moved_ship, t_days)
            _, iq, ir = ship_system_and_pos_at(s, t_days)
            sys_node.ships[i] = CampaignShip(
                ship_id=s.ship_id, name=s.name,
                instance=s.instance,
                system_id=s.system_id, q_sh=iq, r_sh=ir,
                owner=s.owner, order_day=t_days, route=new_route,
                intercept_target=s.intercept_target,
            )


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
async def ship_move(node_id: str, ship_id: str, dest_q: int, dest_r: int) -> JSONResponse:
    """Issue an intra-system movement order from the current game time."""
    g = _get_galaxy()
    t_days = g.game_time
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

    updated = CampaignShip(
        ship_id=ship.ship_id, name=ship.name,
        instance=ship.instance,
        system_id=node_id, q_sh=cur_q, r_sh=cur_r,
        owner=ship.owner, order_day=t_days, route=new_route,
        intercept_target=ship.intercept_target,
    )
    idx = node.ships.index(ship)
    node.ships[idx] = updated
    _recalc_intercepts(g, updated, t_days)
    return JSONResponse(_build_orbital_data(node, g))


@router.post("/system/{node_id}/ship/{ship_id}/intercept", response_class=JSONResponse)
async def ship_intercept(node_id: str, ship_id: str, target_id: str) -> JSONResponse:
    """Issue an intercept order: this ship will path to meet target_id."""
    g = _get_galaxy()
    t_days = g.game_time
    node = g.systems.get(node_id)
    if node is None:
        return JSONResponse({"error": "system not found"}, status_code=404)

    ship = next((s for s in node.ships if s.ship_id == ship_id), None)
    if ship is None:
        return JSONResponse({"error": "ship not found"}, status_code=404)

    target = next(
        (s for n in g.systems.values() for s in n.ships if s.ship_id == target_id),
        None,
    )
    if target is None:
        return JSONResponse({"error": "target not found"}, status_code=404)

    new_route = build_intercept_route(g, ship, target, t_days)
    _, cur_q, cur_r = ship_system_and_pos_at(ship, t_days)

    updated = CampaignShip(
        ship_id=ship.ship_id, name=ship.name,
        instance=ship.instance,
        system_id=node_id, q_sh=cur_q, r_sh=cur_r,
        owner=ship.owner, order_day=t_days, route=new_route,
        intercept_target=target_id,
    )
    idx = node.ships.index(ship)
    node.ships[idx] = updated
    return JSONResponse(_build_orbital_data(node, g))


@router.post("/ship/{ship_id}/route", response_class=JSONResponse)
async def ship_route(ship_id: str, dest_system_id: str) -> JSONResponse:
    """Issue an interstellar route order from the galaxy view."""
    g = _get_galaxy()
    t_days = g.game_time

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
    cur_sys, cur_q, cur_r = ship_system_and_pos_at(ship, t_days)

    updated_ship = CampaignShip(
        ship_id=ship.ship_id, name=ship.name,
        instance=ship.instance,
        system_id=cur_sys, q_sh=cur_q, r_sh=cur_r,
        owner=ship.owner, order_day=t_days, route=new_legs,
    )
    idx = ship_node.ships.index(ship)
    ship_node.ships[idx] = updated_ship

    if cur_sys != ship_node.node_id:
        ship_node.ships.pop(idx)
        g.systems[cur_sys].ships.append(updated_ship)

    hops = sum(1 for leg in new_legs if isinstance(leg, TransitLeg))
    return JSONResponse({"ok": True, "hops": hops, "legs": len(new_legs)})


@router.post("/tick", response_class=JSONResponse)
async def tick(t: float) -> JSONResponse:
    """Advance game time to t, stopping early at the first combat collision."""
    import uuid as _uuid
    g = _get_galaxy()
    if t < g.game_time:
        return JSONResponse({"error": "cannot go back in time"}, status_code=400)

    # Block advancement while any engagement is unresolved
    unresolved = [e for e in g.engagements if e.status != EngagementStatus.RESOLVED]
    if unresolved:
        ships_out = _ships_payload(g)
        return JSONResponse({
            "game_time":        g.game_time,
            "ships":            ships_out,
            "paused_for_combat": True,
            "engagements":      [_eng_to_dict(e) for e in unresolved],
        })

    # ---- Collision detection: find earliest hostile hex collision ----
    all_ships = [s for node in g.systems.values() for s in node.ships]
    earliest_t:  float | None = None
    hex_collisions: dict[tuple, set[str]] = {}   # (system, q, r) → ship_ids

    for i in range(len(all_ships)):
        for j in range(i + 1, len(all_ships)):
            a, b = all_ships[i], all_ships[j]
            if a.owner == b.owner:
                continue
            # Extend scan by one hourly step so Python's cube_round
            # can catch collisions that JS detected one step earlier.
            result = find_path_collision(a, b, g.game_time, t + 1 / 24)
            if result is None:
                continue
            col_t, col_sys, col_q, col_r = result
            if earliest_t is None or col_t < earliest_t:
                earliest_t = col_t
                hex_collisions = {}
            if col_t == earliest_t:
                key = (col_sys, col_q, col_r)
                hex_collisions.setdefault(key, set())
                hex_collisions[key].add(a.ship_id)
                hex_collisions[key].add(b.ship_id)

    effective_t = earliest_t if earliest_t is not None else t

    # ---- Advance all ships to effective_t ----
    updates: list[tuple[CampaignShip, str]] = []
    for sys_node in g.systems.values():
        for ship in sys_node.ships:
            new_sys, new_q, new_r = ship_system_and_pos_at(ship, effective_t)
            remaining = [
                leg for leg in ship.route
                if (isinstance(leg, MoveLeg) and leg.arrive_day > effective_t)
                or (isinstance(leg, TransitLeg) and leg.day > effective_t)
            ]
            updates.append((CampaignShip(
                ship_id=ship.ship_id, name=ship.name,
                instance=ship.instance,
                system_id=new_sys, q_sh=new_q, r_sh=new_r,
                owner=ship.owner, order_day=effective_t, route=remaining,
                intercept_target=ship.intercept_target,
            ), new_sys))

    for sys_node in g.systems.values():
        sys_node.ships.clear()
    for updated, new_sys in updates:
        g.systems[new_sys].ships.append(updated)

    g.game_time = effective_t

    # ---- Create Engagement records for every collision hex ----
    new_engagements: list[Engagement] = []
    for (col_sys, col_q, col_r), ship_ids in hex_collisions.items():
        eng = Engagement(
            engagement_id=str(_uuid.uuid4())[:8],
            system_id=col_sys,
            q_sh=col_q,
            r_sh=col_r,
            ship_ids=sorted(ship_ids),
            status=EngagementStatus.PENDING,
            collision_day=effective_t,
        )
        g.engagements.append(eng)
        new_engagements.append(eng)

    ships_out = _ships_payload(g)
    return JSONResponse({
        "game_time":          g.game_time,
        "ships":              ships_out,
        "paused_for_combat":  len(new_engagements) > 0,
        "engagements":        [_eng_to_dict(e) for e in new_engagements],
    })


def _ships_payload(g: Galaxy) -> list[dict]:
    out = []
    for sys_node in g.systems.values():
        for s in sys_node.ships:
            out.append({
                "ship_id":          s.ship_id,
                "name":             s.name,
                "hull_type":        s.instance.design.hull_type_id,
                "owner":            s.owner,
                "system_id":        s.system_id,
                "q_sh":             s.q_sh,
                "r_sh":             s.r_sh,
                "sH_per_day":       s.sH_per_day,
                "intercept_target": s.intercept_target,
                "legs":             _serialize_legs(s.route),
            })
    return out


@router.post("/engagement/{engagement_id}/auto-resolve", response_class=JSONResponse)
async def engagement_auto_resolve(engagement_id: str) -> JSONResponse:
    """Coin-flip auto-resolution: destroy the losing side, mark engagement resolved."""
    import random as _random
    g = _get_galaxy()
    eng = next((e for e in g.engagements if e.engagement_id == engagement_id), None)
    if eng is None:
        return JSONResponse({"error": "engagement not found"}, status_code=404)
    if eng.status == EngagementStatus.RESOLVED:
        return JSONResponse({"error": "already resolved"}, status_code=400)

    result = auto_resolve_stub(eng, g, _random.Random())

    # Remove destroyed ships from all system ship lists
    destroyed_set = set(result["destroyed"])
    for sys_node in g.systems.values():
        sys_node.ships[:] = [s for s in sys_node.ships if s.ship_id not in destroyed_set]

    # Mark resolved
    idx = g.engagements.index(eng)
    g.engagements[idx] = Engagement(
        engagement_id=eng.engagement_id,
        system_id=eng.system_id,
        q_sh=eng.q_sh, r_sh=eng.r_sh,
        ship_ids=eng.ship_ids,
        status=EngagementStatus.RESOLVED,
        collision_day=eng.collision_day,
        tactical_game_id=eng.tactical_game_id,
    )

    return JSONResponse({**result, "engagement_id": engagement_id, "status": "resolved"})


@router.post("/engagement/{engagement_id}/start-tactical", response_class=JSONResponse)
async def engagement_start_tactical(engagement_id: str) -> JSONResponse:
    """Build a tactical encounter from the engagement and return its game URL."""
    from tactical.web import create_game_from_battle
    g = _get_galaxy()
    eng = next((e for e in g.engagements if e.engagement_id == engagement_id), None)
    if eng is None:
        return JSONResponse({"error": "engagement not found"}, status_code=404)
    if eng.status == EngagementStatus.RESOLVED:
        return JSONResponse({"error": "already resolved"}, status_code=400)

    battle, rng = build_battle_from_engagement(eng, g)
    game_id = create_game_from_battle(
        name=f"Combat {eng.engagement_id} @ {eng.system_id}",
        battle=battle,
        rng=rng,
    )

    # Mark in-progress and record the tactical game id
    idx = g.engagements.index(eng)
    g.engagements[idx] = Engagement(
        engagement_id=eng.engagement_id,
        system_id=eng.system_id,
        q_sh=eng.q_sh, r_sh=eng.r_sh,
        ship_ids=eng.ship_ids,
        status=EngagementStatus.IN_PROGRESS,
        collision_day=eng.collision_day,
        tactical_game_id=game_id,
    )

    return JSONResponse({
        "game_id":  game_id,
        "url":      f"/tactical/?game_id={game_id}",
        "ship_ids": eng.ship_ids,
    })

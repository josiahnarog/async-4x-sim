"""Campaign web routes.

Endpoints:
    GET  /campaign/             → galaxy overview (force-layout graph)
    GET  /campaign/new          → regenerate galaxy, redirect to /campaign/
    GET  /campaign/system/{id}  → system detail (polar sH map)
    GET  /campaign/api/galaxy   → JSON galaxy data for JS renderer
"""

from __future__ import annotations

import math
import random
from typing import Optional

from fastapi import APIRouter
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from campaign.generator import generate_system_with_companions
from campaign.linker import build_galaxy
from campaign.models import (
    AnomalyType,
    Galaxy,
    MoonType,
    Planet,
    PlanetType,
    SpectralClass,
    Star,
    SystemNode,
    WPVisibility,
)

router = APIRouter(prefix="/campaign")
templates = Jinja2Templates(directory="templates")

# ---------------------------------------------------------------------------
# In-memory galaxy store
# ---------------------------------------------------------------------------

_galaxy: Optional[Galaxy] = None
_galaxy_seed: int = 42


def _make_galaxy(seed: int, n_systems: int = 24) -> Galaxy:
    rng = random.Random(seed)
    systems: dict[str, SystemNode] = {}
    for i in range(n_systems):
        node_id = f"SYS-{i + 1:04d}"
        r = rng.random()
        add_bin = r < 0.30
        add_tri = add_bin and rng.random() < 0.15
        node = generate_system_with_companions(
            rng, node_id, add_binary=add_bin, add_trinary=add_tri
        )
        systems[node_id] = node
    return build_galaxy(systems, rng)


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
    WPVisibility.OPEN.value:      "#44ddff",
    WPVisibility.CONCEALED.value: "#ffaa44",
    WPVisibility.HIDDEN.value:    "#ff4444",
    WPVisibility.SECRET.value:    "#aa44ff",
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
        })

    edges = []
    for e in g.edges:
        edges.append({
            "a":     node_index[e.system_a],
            "b":     node_index[e.system_b],
            "wp_a":  e.wp_a,
            "wp_b":  e.wp_b,
        })

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# Polar SVG helpers for system view
# ---------------------------------------------------------------------------

_SVG_CX  = 480
_SVG_CY  = 480
_SVG_W   = 960
_SVG_H   = 960


def _sqrt_r(dist_sh: float, scale: float = 90.0) -> float:
    """Convert sH distance to SVG radius using sqrt scale."""
    return scale * math.sqrt(max(dist_sh, 0.1))


def _bearing_to_xy(bearing: int, r_px: float) -> tuple[float, float]:
    """Convert 1-12 bearing sector + radius to SVG (x, y)."""
    # Sector 1 = north (up), clockwise. SVG 0° = east, 90° = south.
    angle_deg = (bearing - 1) * 30 - 90
    rad = math.radians(angle_deg)
    return (_SVG_CX + r_px * math.cos(rad), _SVG_CY + r_px * math.sin(rad))


_GOLDEN_ANGLE = 137.508  # degrees


def _orbit_angle(orbit_slot: int) -> float:
    """Assign a visually spread angle to a planet by orbit slot."""
    return math.radians(_GOLDEN_ANGLE * orbit_slot - 90)


def _planet_xy(distance_sh: int, orbit_slot: int) -> tuple[float, float]:
    r = _sqrt_r(distance_sh)
    a = _orbit_angle(orbit_slot)
    return (_SVG_CX + r * math.cos(a), _SVG_CY + r * math.sin(a))


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _render_system_svg(node: SystemNode) -> str:
    parts: list[str] = []

    def e(tag: str, **attrs) -> str:
        attr_str = " ".join(
            f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items() if v is not None
        )
        return f"<{tag} {attr_str}/>"

    def g(inner: str, **attrs) -> str:
        attr_str = " ".join(
            f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items()
        )
        return f"<g {attr_str}>{inner}</g>"

    # Background
    parts.append(f'<rect width="{_SVG_W}" height="{_SVG_H}" fill="#060612"/>')

    # Orbit rings for each planet distance
    primary = node.primary
    if primary and primary.spectral_class:
        # Draw thin orbit rings for each planet in the primary star's system
        for star in node.stars:
            for p in star.planets:
                r = _sqrt_r(p.distance_sh)
                parts.append(
                    f'<circle cx="{_SVG_CX}" cy="{_SVG_CY}" r="{r:.1f}" '
                    f'fill="none" stroke="#1a2040" stroke-width="1"/>'
                )

    # WP lines from center
    for wp in node.warp_points:
        r = _sqrt_r(wp.distance_sh)
        x, y = _bearing_to_xy(wp.bearing, r)
        col = _WP_VIS_COLOURS.get(wp.visibility.value, "#44ddff")
        parts.append(
            f'<line x1="{_SVG_CX}" y1="{_SVG_CY}" x2="{x:.1f}" y2="{y:.1f}" '
            f'stroke="{col}" stroke-width="0.5" stroke-dasharray="4,4" opacity="0.5"/>'
        )

    # Stars
    for star in node.stars:
        if star.component == "A":
            cx, cy = _SVG_CX, _SVG_CY
        elif star.bearing is not None:
            r = _sqrt_r(star.distance_sh)
            cx, cy = _bearing_to_xy(star.bearing, r)
        else:
            continue

        if star.anomaly_type is not None:
            col = "#aa44ff"
            lbl = star.anomaly_type.value[:3].upper()
        elif star.spectral_class is not None:
            col = _SPECTRAL_COLOURS.get(star.spectral_class.value, "#ffffff")
            lbl = star.component
        else:
            col = "#888888"
            lbl = star.component

        radius = 18 if star.component == "A" else 12
        parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius}" fill="{col}" '
            f'stroke="#ffffff" stroke-width="1" opacity="0.9"/>'
        )
        parts.append(
            f'<text x="{cx:.1f}" y="{cy + radius + 13:.1f}" '
            f'text-anchor="middle" fill="#cccccc" font-size="11" font-family="monospace">'
            f'{_escape(lbl)}</text>'
        )

    # Planets
    for star in node.stars:
        for p in star.planets:
            x, y = _planet_xy(p.distance_sh, p.orbit_slot)
            col = _PLANET_COLOURS.get(p.planet_type.value, "#888888")

            if p.planet_type == PlanetType.AST:
                # Asteroid belt: small dots around the ring position
                parts.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="none" '
                    f'stroke="{col}" stroke-width="2"/>'
                )
            else:
                pr = 6 if p.mass == 3 else (5 if p.mass == 2 else 4)
                parts.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{pr}" fill="{col}" '
                    f'stroke="#ffffff" stroke-width="0.5"/>'
                )

            # Planet label
            label = p.planet_type.value
            if p.hi is not None:
                label += f" HI{p.hi}"
            parts.append(
                f'<text x="{x:.1f}" y="{y - 8:.1f}" text-anchor="middle" '
                f'fill="#aaaaaa" font-size="9" font-family="monospace">{_escape(label)}</text>'
            )

            # Moon count indicator
            if p.moons:
                parts.append(
                    f'<text x="{x + 8:.1f}" y="{y + 4:.1f}" '
                    f'fill="#778899" font-size="8" font-family="monospace">'
                    f'×{len(p.moons)}</text>'
                )

    # Warp points
    for wp in node.warp_points:
        r = _sqrt_r(wp.distance_sh)
        x, y = _bearing_to_xy(wp.bearing, r)
        col = _WP_VIS_COLOURS.get(wp.visibility.value, "#44ddff")
        # Diamond shape
        s = 7
        pts = f"{x:.1f},{y - s:.1f} {x + s:.1f},{y:.1f} {x:.1f},{y + s:.1f} {x - s:.1f},{y:.1f}"
        parts.append(f'<polygon points="{pts}" fill="{col}" stroke="#ffffff" stroke-width="0.5" opacity="0.85"/>')
        link_label = f"→{wp.linked_to[0]}" if wp.linked_to else "?"
        parts.append(
            f'<text x="{x:.1f}" y="{y + s + 12:.1f}" text-anchor="middle" '
            f'fill="{col}" font-size="9" font-family="monospace">{_escape(link_label)}</text>'
        )

    # Bearing compass (light ring)
    parts.append(
        f'<circle cx="{_SVG_CX}" cy="{_SVG_CY}" r="440" fill="none" '
        f'stroke="#1a2040" stroke-width="1"/>'
    )
    for sector in range(1, 13):
        angle_deg = (sector - 1) * 30 - 90
        rad = math.radians(angle_deg)
        x1 = _SVG_CX + 435 * math.cos(rad)
        y1 = _SVG_CY + 435 * math.sin(rad)
        x2 = _SVG_CX + 448 * math.cos(rad)
        y2 = _SVG_CY + 448 * math.sin(rad)
        xl = _SVG_CX + 460 * math.cos(rad)
        yl = _SVG_CY + 460 * math.sin(rad)
        parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#334" stroke-width="1"/>')
        parts.append(
            f'<text x="{xl:.1f}" y="{yl + 4:.1f}" text-anchor="middle" '
            f'fill="#334466" font-size="9" font-family="monospace">{sector}</text>'
        )

    return "\n".join(parts)


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
    for star in node.stars:
        for p in star.planets:
            hi_str = f" HI={p.hi}" if p.hi is not None else ""
            tl_str = " [tidelock]" if p.tidelock else ""
            atm_str = " [atm]" if p.has_atmosphere else ""
            moon_str = f" {len(p.moons)}☽" if p.moons else ""
            planet_info.append(
                f"Orbit {p.orbit_slot:2d} @ {p.distance_sh:4d}sH  "
                f"{p.planet_type.value:3s}  M{p.mass or '-'}"
                f"{hi_str}{tl_str}{atm_str}{moon_str}  [{star.component}]"
            )

    wp_info = []
    for wp in node.warp_points:
        dest = wp.linked_to[0] if wp.linked_to else "unlinked"
        wp_info.append(
            f"{wp.wp_id}  bearing={wp.bearing:2d}  dist={wp.distance_sh:3d}sH  "
            f"{wp.visibility.value:10s}  → {dest}"
        )

    return templates.TemplateResponse(
        "campaign_system.html",
        {
            "request":    request,
            "node_id":    node_id,
            "svg":        svg_content,
            "star_info":  star_info,
            "planet_info": planet_info,
            "wp_info":    wp_info,
            "svg_w":      _SVG_W,
            "svg_h":      _SVG_H,
        },
    )

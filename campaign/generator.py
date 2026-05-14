"""System generation pipeline.

Entry point:
    generate_system(rng, node_id, category) -> SystemNode

Generation order (from Starfire rules):
  1.  Assign node ID  (caller responsibility)
  2.  Roll system type / spectral class; check for anomaly
  3.  Roll stars (primary A; optionally binary B, trinary C)
  4.  Roll orbits and planets for each star with planets possible
  5.  Apply binary AST disruption (planets too close to companion)
  6.  Roll WP quantity, distance, bearing, and visibility
  7.  Apply Gas Giant AST conversion (outmost first, 20% chance each)
  8.  Apply WP–planet collision AST conversion
  9.  Roll moons for each surviving non-AST planet
  10. (Nebula effects — not yet implemented)
  11. (WP linking — handled by campaign.linker after all nodes are generated)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional

from campaign.hex_utils import (
    bearing_dist_to_axial,
    cube_round,
    orbit_screen_pos,
    screen_to_axial_frac,
)
from campaign.models import (
    AnomalyType,
    Galaxy,
    GalaxyEdge,
    LM_PER_SH,
    Moon,
    MoonType,
    Planet,
    PlanetType,
    Population,
    SpectralClass,
    Star,
    SystemCategory,
    SystemNode,
    WarpPoint,
    WPVisibility,
)
from campaign.tables import (
    classify_orbit,
    get_zone_bounds,
    moon_count_modifier,
    roll_anomaly_type,
    roll_moon_count,
    roll_orbit_distances,
    roll_planet,
    roll_spectral_class,
    roll_wp_count,
    roll_wp_distance,
    roll_wp_visibility,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _roll(rng: random.Random, sides: int) -> int:
    return rng.randint(1, sides)


def _roll_orbit_pair(rng: random.Random) -> tuple[int | None, ...]:
    """Roll 2d10 repeatedly until the gap >= 2; return the orbit distance tuple."""
    for _ in range(50):  # safety limit
        d1 = _roll(rng, 10)
        d2 = _roll(rng, 10)
        result = roll_orbit_distances(d1, d2)
        if result is not None:
            return result
    # Fallback: minimum valid pair (roll_orbit_distances converts LM→sH)
    return roll_orbit_distances(1, 3) or tuple(
        max(1, round(v / LM_PER_SH)) for v in (12, 36, 60, 108, 204, 396, 780, 1548, 3084)
    )


def _moon_type_for(planet_type: PlanetType) -> MoonType:
    if planet_type in {PlanetType.H, PlanetType.V}:
        return MoonType.mH
    if planet_type in {PlanetType.F, PlanetType.I}:
        return MoonType.mF
    return MoonType.mB


def _has_atmosphere(planet_type: PlanetType, mass: int | None) -> bool:
    """Mass 2+ B and H worlds have atmospheres for weapons-fire purposes."""
    return planet_type in {PlanetType.B, PlanetType.H} and mass is not None and mass >= 2


# ---------------------------------------------------------------------------
# Orbital / hex-coord helpers
# ---------------------------------------------------------------------------

# Approximate stellar masses in solar units, used for Keplerian period calc.
_STAR_MASS_SOLAR: dict[SpectralClass, float] = {
    SpectralClass.WHITE:        2.0,
    SpectralClass.YELLOW_WHITE: 1.5,
    SpectralClass.YELLOW:       1.0,
    SpectralClass.ORANGE:       0.7,
    SpectralClass.RED:          0.4,
    SpectralClass.RED_DWARF:    0.2,
    SpectralClass.BLUE_GIANT:  10.0,
    SpectralClass.WHITE_DWARF:  0.6,
    SpectralClass.RED_GIANT:    1.2,
}

# The Starfire orbit table labels distances in "LM" but those values are ~11×
# larger than real light-minutes (Yellow biosphere 72–144 game-LM corresponds
# to 0.9–1.5 AU in real physics).  Using the raw 8.317 LM/AU conversion puts
# the biosphere at 8–17 AU and gives 25–72 year orbital periods.
# Correct scale: Yellow biosphere midpoint (18 sH) ≈ 1.2 AU → 6/90 AU/sH.
_SH_TO_AU: float = LM_PER_SH / 90.0

# 1 TH = 1/2880 sH.  TH physical size is fixed at the LM_PER_SH=12 reference scale
# so moon orbital periods are independent of the strategic-hex scale setting.
# At that reference: 1 TH = 12/2880 LM ≈ 74,948 km  (Earth-Moon ≈ 5.1 TH → ~27 day period)
_TH_TO_KM: float = (12 / 2880.0) * 17_987_547.5


def _orbital_period_years(distance_sh: int, star_mass_solar: float) -> float:
    """Keplerian period (years): T = (a_AU)^1.5 / sqrt(M_solar)."""
    if star_mass_solar <= 0 or distance_sh <= 0:
        return 0.0
    a_au = distance_sh * _SH_TO_AU
    return (a_au ** 1.5) / math.sqrt(star_mass_solar)


def _moon_period_days(orbit_th: int) -> float:
    """Approximate moon orbital period (Earth days) via Earth-Moon scaling."""
    if orbit_th <= 0:
        return 0.0
    a_km = orbit_th * _TH_TO_KM
    return 27.3 * (a_km / 384_400.0) ** 1.5


_GOLDEN_ANGLE_DEG: float = 137.508   # degrees; evenly spreads orbit slots angularly


def _assign_planet_coords(
    planets: list[Planet],
    star_q: int,
    star_r: int,
    star_mass_solar: float,
) -> None:
    """Set q_sh, r_sh, orbital_angle_0, orbital_period_years on each planet.

    Each planet's orbital_angle_0 is set to a golden-angle spread over orbit
    slots.  q_sh/r_sh are the nearest axial hex to the true circular orbit
    position at that angle (not constrained to the hex ring).  Coordinates are
    absolute (relative to system primary at (0,0)).
    """
    for p in planets:
        angle = (_GOLDEN_ANGLE_DEG * p.orbit_slot) % 360.0
        x, y = orbit_screen_pos(angle, p.distance_sh)
        q_rel, r_rel = cube_round(*screen_to_axial_frac(x, y))
        p.q_sh = star_q + q_rel
        p.r_sh = star_r + r_rel
        p.orbital_angle_0 = angle
        p.orbital_period_years = _orbital_period_years(p.distance_sh, star_mass_solar)


def _assign_moon_coords(moons: list[Moon]) -> None:
    """Set q_th, r_th, orbital_angle_0, orbital_period_days on each moon.

    Moons are spread evenly in angle around the planet (TH space).  q_th/r_th
    are the nearest axial hex to the circular orbit position at that angle.
    """
    n = len(moons)
    for i, moon in enumerate(moons):
        angle = (360.0 * i / n) if n > 1 else 0.0
        x, y = orbit_screen_pos(angle, moon.orbit_th)
        moon.q_th, moon.r_th = cube_round(*screen_to_axial_frac(x, y))
        moon.orbital_angle_0 = angle
        moon.orbital_period_days = _moon_period_days(moon.orbit_th)


def _star_mass(star: Star) -> float:
    """Return solar mass for a star; 1.0 if spectral class is unknown."""
    if star.spectral_class is not None:
        return _STAR_MASS_SOLAR.get(star.spectral_class, 1.0)
    return 1.0


def _expand_ast_belt(
    planet: Planet,
    star_q: int,
    star_r: int,
    star_mass_solar: float,
) -> list[Planet]:
    """Expand a single AST Planet into evenly-spaced segments around a circular orbit.

    Uses the same segment count as the hex ring (6 × distance_sh) so belt
    density is preserved.  Angles are uniformly distributed; q_sh/r_sh snap to
    the nearest axial hex of the circular position.  All segments share the
    same orbital_period_years so the belt rotates as a rigid ring.
    """
    n_segments = 6 * planet.distance_sh
    period = _orbital_period_years(planet.distance_sh, star_mass_solar)
    belt_hexes: list[Planet] = []
    for i in range(n_segments):
        angle = 360.0 * i / n_segments
        x, y = orbit_screen_pos(angle, planet.distance_sh)
        q_rel, r_rel = cube_round(*screen_to_axial_frac(x, y))
        belt_hexes.append(Planet(
            orbit_slot=planet.orbit_slot,
            distance_sh=planet.distance_sh,
            planet_type=PlanetType.AST,
            mass=None,
            parent_star=planet.parent_star,
            q_sh=star_q + q_rel,
            r_sh=star_r + r_rel,
            orbital_angle_0=angle,
            orbital_period_years=period,
        ))
    return belt_hexes


def _finalize_coords(node: "SystemNode") -> None:
    """Assign canonical hex coordinates to all objects in a system node.

    Called at the end of generation (after all disruption passes) so that
    only surviving objects receive coordinates.  Safe to call multiple times
    (idempotent — overwrites previous values).
    """
    primary = node.primary  # Star A, always at (0, 0)
    primary_mass = _star_mass(primary) if primary else 1.0

    for star in node.stars:
        if star.component == "A":
            star.q_sh, star.r_sh = 0, 0
            # A does not orbit
        elif star.bearing is not None:
            star.q_sh, star.r_sh = bearing_dist_to_axial(star.bearing, star.distance_sh)
            star.orbital_angle_0 = (star.bearing - 1) * 30.0
            star.orbital_period_years = _orbital_period_years(
                star.distance_sh, primary_mass
            )

        # Assign planet coords relative to this star's position
        mass = _star_mass(star)
        _assign_planet_coords(
            star.planets,
            star_q=star.q_sh,
            star_r=star.r_sh,
            star_mass_solar=mass,
        )
        for p in star.planets:
            _assign_moon_coords(p.moons)

    # WPs are fixed relative to primary (no orbital motion)
    for wp in node.warp_points:
        wp.q_sh, wp.r_sh = bearing_dist_to_axial(wp.bearing, wp.distance_sh)


def _expand_all_ast_belts(node: "SystemNode") -> None:
    """Expand every single-hex AST planet into a full ring of belt hexes.

    Called once, after the final _finalize_coords pass, so coords are already
    authoritative and disruption passes are complete.  Must NOT be called
    inside _finalize_coords (which may be invoked multiple times during
    companion generation).
    """
    for star in node.stars:
        mass = _star_mass(star)
        expanded: list[Planet] = []
        for p in star.planets:
            if p.planet_type == PlanetType.AST:
                expanded.extend(_expand_ast_belt(p, star.q_sh, star.r_sh, mass))
            else:
                expanded.append(p)
        star.planets = expanded


# ---------------------------------------------------------------------------
# Step 4a: Planet generation for one star
# ---------------------------------------------------------------------------

def _generate_planets(
    rng: random.Random,
    star: Star,
    component: str,
) -> list[Planet]:
    """Roll orbits and generate planet objects for a single star."""
    if not star.has_planets_possible:
        return []

    orbit_distances = _roll_orbit_pair(rng)
    bounds = get_zone_bounds(star.spectral_class)  # type: ignore[arg-type]
    if bounds is None:
        return []

    tl_lo, tl_hi = bounds["tidelock"]
    planets: list[Planet] = []

    for slot_idx, dist in enumerate(orbit_distances, start=1):
        if dist is None:
            continue

        zone_sub = classify_orbit(star.spectral_class, dist)  # type: ignore[arg-type]
        if zone_sub == "beyond":
            continue

        mass, ptype = roll_planet(_roll(rng, 100), zone_sub)
        if ptype is None:
            continue

        # B worlds in the Hot Rocky Zone become H planets
        if ptype == PlanetType.B and zone_sub == "hot":
            ptype = PlanetType.H

        is_tidelock = (tl_lo <= dist <= tl_hi)
        atmo        = _has_atmosphere(ptype, mass)

        hi: Optional[int] = None
        if ptype in {PlanetType.T, PlanetType.ST}:
            hi = _roll(rng, 10)

        planets.append(Planet(
            orbit_slot=slot_idx,
            distance_sh=dist,
            planet_type=ptype,
            mass=mass,
            has_atmosphere=atmo,
            tidelock=is_tidelock,
            hi=hi,
            parent_star=component,
        ))

    return planets


# ---------------------------------------------------------------------------
# Step 5: Binary AST disruption
# ---------------------------------------------------------------------------

def _apply_binary_disruption(
    planets: list[Planet],
    separation_sh: int,
) -> list[Planet]:
    """Remove or convert planets disrupted by a binary companion.

    Thresholds (from primary star perspective):
      distance > separation / 3 → removed
      distance > separation / 4 → converted to AST
    """
    remove_threshold = separation_sh / 3
    ast_threshold    = separation_sh / 4

    result: list[Planet] = []
    for p in planets:
        if p.distance_sh > remove_threshold:
            pass  # removed — do not append
        elif p.distance_sh > ast_threshold:
            result.append(Planet(
                orbit_slot=p.orbit_slot,
                distance_sh=p.distance_sh,
                planet_type=PlanetType.AST,
                mass=None,
                parent_star=p.parent_star,
            ))
        else:
            result.append(p)
    return result


# ---------------------------------------------------------------------------
# Step 7: Gas Giant AST conversion
# ---------------------------------------------------------------------------

def _apply_gas_giant_disruption(
    planets: list[Planet],
    rng: random.Random,
) -> list[Planet]:
    """Each G planet (outermost first) has 20% chance to convert the planet
    just inside it to AST.  G planets already converted do not roll.
    """
    # Work from outermost to innermost
    sorted_planets = sorted(planets, key=lambda p: p.distance_sh, reverse=True)

    # Build index for quick distance lookup
    by_dist = {p.distance_sh: i for i, p in enumerate(sorted_planets)}

    converted: set[int] = set()  # indices in sorted_planets

    for i, p in enumerate(sorted_planets):
        if p.planet_type != PlanetType.G:
            continue
        if i in converted:
            continue  # already an AST, doesn't roll
        # Find the planet just inside (next in the descending list)
        if i + 1 < len(sorted_planets):
            inner_idx = i + 1
            if rng.random() < 0.20:
                converted.add(inner_idx)

    result: list[Planet] = []
    for i, p in enumerate(sorted_planets):
        if i in converted:
            result.append(Planet(
                orbit_slot=p.orbit_slot,
                distance_sh=p.distance_sh,
                planet_type=PlanetType.AST,
                mass=None,
                parent_star=p.parent_star,
            ))
        else:
            result.append(p)

    # Restore original (innermost-first) order
    return sorted(result, key=lambda p: p.distance_sh)


# ---------------------------------------------------------------------------
# Step 8: WP–planet collision AST conversion
# ---------------------------------------------------------------------------

def _apply_wp_collision(
    planets: list[Planet],
    warp_points: list[WarpPoint],
) -> list[Planet]:
    """Convert any planet at the same sH distance as a WP to AST."""
    wp_distances = {wp.distance_sh for wp in warp_points}
    result: list[Planet] = []
    for p in planets:
        if p.distance_sh in wp_distances and p.planet_type != PlanetType.AST:
            result.append(Planet(
                orbit_slot=p.orbit_slot,
                distance_sh=p.distance_sh,
                planet_type=PlanetType.AST,
                mass=None,
                parent_star=p.parent_star,
            ))
        else:
            result.append(p)
    return result


# ---------------------------------------------------------------------------
# Step 9: Moon generation
# ---------------------------------------------------------------------------

def _generate_moons(rng: random.Random, planet: Planet) -> list[Moon]:
    """Roll and place moons for a single planet."""
    if planet.planet_type == PlanetType.AST:
        return []

    count = roll_moon_count(_roll(rng, 100), planet.planet_type, planet.mass)
    if count == 0:
        return []

    mtype = _moon_type_for(planet.planet_type)
    is_gas = planet.planet_type in {PlanetType.G, PlanetType.I}

    moons: list[Moon] = []
    cumulative_th = 0

    for _ in range(count):
        if is_gas:
            if not moons:
                orbit_th = max(1, _roll(rng, 10) // 2)  # 1d10/2 FRU
            else:
                orbit_th = cumulative_th + _roll(rng, 10)
        else:
            step = max(1, (_roll(rng, 10) + 2) // 3)  # 1d10/3 FRU
            orbit_th = (cumulative_th + step) if moons else step

        cumulative_th = orbit_th
        moons.append(Moon(moon_type=mtype, orbit_th=orbit_th))

    # Big moon check for T/ST planets
    if planet.planet_type in {PlanetType.T, PlanetType.ST} and moons:
        if _roll(rng, 100) <= 3:
            big_idx = rng.randrange(len(moons))
            m = moons[big_idx]
            moons[big_idx] = Moon(
                moon_type=m.moon_type,
                orbit_th=m.orbit_th,
                is_big=True,
                hi=_roll(rng, 10),
            )

    return moons


# ---------------------------------------------------------------------------
# WP generation (Step 6)
# ---------------------------------------------------------------------------

def _generate_warp_points(
    rng: random.Random,
    node_id: str,
    category: str,
) -> list[WarpPoint]:
    """Roll WP count, then generate each WP."""
    roll100 = _roll(rng, 100)
    roll10  = _roll(rng, 10)
    count   = roll_wp_count(roll100, category, roll10)

    wps: list[WarpPoint] = []
    for i in range(count):
        bearing    = _roll(rng, 12)
        dist       = roll_wp_distance(_roll(rng, 100))
        visibility = roll_wp_visibility(_roll(rng, 10))
        wps.append(WarpPoint(
            wp_id=f"{node_id}-WP{i + 1}",
            bearing=bearing,
            distance_sh=dist,
            visibility=visibility,
        ))
    return wps


# ---------------------------------------------------------------------------
# Star generation
# ---------------------------------------------------------------------------

def _generate_star(
    rng: random.Random,
    component: str,
    force_spectral: Optional[SpectralClass] = None,
) -> Star:
    """Generate a single star component (A, B, or C)."""
    if force_spectral is not None:
        return Star(component=component, spectral_class=force_spectral)

    roll       = _roll(rng, 100)
    sc, is_ano = roll_spectral_class(roll)
    if is_ano:
        atype = roll_anomaly_type(_roll(rng, 100))
        return Star(component=component, anomaly_type=atype)
    return Star(component=component, spectral_class=sc)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def _build_system_node(
    rng: random.Random,
    node_id: str,
    category: SystemCategory = SystemCategory.NORMAL,
    force_spectral_a: Optional[SpectralClass] = None,
) -> SystemNode:
    """Core generation — star, planets, WPs, moons, coords.

    AST planets are left as single-hex placeholders here.  Callers must
    invoke _expand_all_ast_belts() after all disruption passes are done.
    """
    node = SystemNode(node_id=node_id)

    if category == SystemCategory.STARLESS:
        node.warp_points = _generate_warp_points(rng, node_id, "starless")
        return node

    # -- Primary star -------------------------------------------------
    star_a = _generate_star(rng, "A", force_spectral=force_spectral_a)
    node.stars.append(star_a)

    # -- Planets for A ------------------------------------------------
    star_a.planets = _generate_planets(rng, star_a, "A")

    # -- Determine WP category before disruption changes planet list ---
    has_any_planets = bool(star_a.planets)
    wp_cat = "without_planets" if not has_any_planets else "with_planets"
    if not star_a.has_planets_possible:
        wp_cat = "without_planets"
    node.warp_points = _generate_warp_points(rng, node_id, wp_cat)

    # -- Gas Giant AST conversion -------------------------------------
    star_a.planets = _apply_gas_giant_disruption(star_a.planets, rng)

    # -- WP–planet collision ------------------------------------------
    star_a.planets = _apply_wp_collision(star_a.planets, node.warp_points)

    # -- Moons --------------------------------------------------------
    for p in star_a.planets:
        p.moons = _generate_moons(rng, p)

    # -- Coords (single-hex AST; expansion happens after this) --------
    _finalize_coords(node)

    return node


@dataclass
class SystemSpec:
    """Constraints for a named system node.  Fields left at defaults roll normally.

    Add an entry to the `system_overrides` dict in `_make_galaxy` for each
    system that needs controlled generation (home worlds, NPC capitals, etc.).
    """
    spectral_class:     Optional[SpectralClass] = None  # None → roll table
    guaranteed_terran:  bool                    = False  # retry until ≥1 T/ST survives
    starting_population: Optional[Population]   = None   # placed on first T/ST planet
    add_binary:         bool                    = False
    add_trinary:        bool                    = False  # requires add_binary


HUMAN_HOME_SPEC = SystemSpec(
    spectral_class=SpectralClass.YELLOW,
    guaranteed_terran=True,
    starting_population=Population(owner="human", size=3, industry=3),
)


def _has_terran(node: SystemNode) -> bool:
    return any(
        p.planet_type in {PlanetType.T, PlanetType.ST}
        for s in node.stars
        for p in s.planets
    )


def _inject_terran(node: SystemNode, rng: random.Random) -> None:
    """Fallback: replace the first non-AST planet with a T planet.

    Called only when retry exhaustion leaves no Terran world.  Picks the
    first surviving non-AST orbit slot on star A and overwrites its type.
    If star A has no surviving planets, appends one at a fixed inner orbit.
    """
    primary = node.primary
    if primary is None:
        return
    candidates = [p for p in primary.planets if p.planet_type != PlanetType.AST]
    if candidates:
        p = candidates[0]
        p.planet_type = PlanetType.T
        p.mass = 2
        p.hi = _roll(rng, 10)
    else:
        primary.planets.append(Planet(
            orbit_slot=1,
            distance_sh=5,
            planet_type=PlanetType.T,
            mass=2,
            hi=_roll(rng, 10),
            parent_star="A",
        ))


def _apply_starting_population(node: SystemNode, spec: "SystemSpec") -> None:
    if spec.starting_population is None:
        return
    for star in node.stars:
        for p in star.planets:
            if p.planet_type in {PlanetType.T, PlanetType.ST}:
                p.population = spec.starting_population
                return


def build_system_from_spec(
    rng: random.Random,
    node_id: str,
    spec: SystemSpec,
    *,
    max_retries: int = 20,
) -> SystemNode:
    """Generate a system satisfying the constraints in `spec`."""
    node: SystemNode = SystemNode(node_id=node_id)  # silences unbound warning
    for _ in range(max_retries):
        node = _build_system_node(rng, node_id, force_spectral_a=spec.spectral_class)

        if spec.add_binary:
            star_a = node.primary
            if star_a is not None:
                star_b = _generate_star(rng, "B")
                star_b.bearing     = _roll(rng, 12)
                star_b.distance_sh = max(1, round((_roll(rng, 12) + _roll(rng, 12) + 5) * 12 / LM_PER_SH))
                star_b.planets     = _generate_planets(rng, star_b, "B")
                star_a.planets     = _apply_binary_disruption(star_a.planets, star_b.distance_sh)
                star_b.planets     = _apply_binary_disruption(star_b.planets, star_b.distance_sh)
                star_b.planets     = _apply_gas_giant_disruption(star_b.planets, rng)
                star_b.planets     = _apply_wp_collision(star_b.planets, node.warp_points)
                for p in star_b.planets:
                    p.moons = _generate_moons(rng, p)
                node.stars.append(star_b)

                if spec.add_trinary:
                    star_c = _generate_star(rng, "C")
                    star_c.bearing     = _roll(rng, 12)
                    star_c.distance_sh = max(1, round((_roll(rng, 4) + 1) * 360 / LM_PER_SH))
                    node.stars.append(star_c)

        _finalize_coords(node)
        _expand_all_ast_belts(node)

        if not spec.guaranteed_terran or _has_terran(node):
            _apply_starting_population(node, spec)
            return node

    # Retry exhaustion — patch in a Terran world and return
    _inject_terran(node, rng)
    _finalize_coords(node)
    _apply_starting_population(node, spec)
    return node


def generate_system(
    rng: random.Random,
    node_id: str,
    category: SystemCategory = SystemCategory.NORMAL,
) -> SystemNode:
    """Generate a complete system node with fully expanded asteroid belts."""
    node = _build_system_node(rng, node_id, category)
    _expand_all_ast_belts(node)
    return node


def generate_system_with_companions(
    rng: random.Random,
    node_id: str,
    add_binary: bool = False,
    add_trinary: bool = False,
) -> SystemNode:
    """Generate a system including optional binary and trinary companions.

    add_binary  — if True, generate Component B star + planets.
    add_trinary — if True (requires add_binary), generate Component C star.

    AST belt expansion happens exactly once, after all disruption passes.
    """
    node = _build_system_node(rng, node_id)
    if not node.stars:
        _expand_all_ast_belts(node)
        return node

    star_a = node.primary
    if star_a is None:
        _expand_all_ast_belts(node)
        return node

    if add_binary:
        star_b = _generate_star(rng, "B")
        star_b.bearing     = _roll(rng, 12)
        star_b.distance_sh = max(1, round((_roll(rng, 12) + _roll(rng, 12) + 5) * 12 / LM_PER_SH))

        # Planets for B
        star_b.planets = _generate_planets(rng, star_b, "B")

        # Apply binary disruption to A's planets (too close to B)
        star_a.planets = _apply_binary_disruption(star_a.planets, star_b.distance_sh)
        # Apply binary disruption to B's planets (too close to A)
        star_b.planets = _apply_binary_disruption(star_b.planets, star_b.distance_sh)

        # Gas Giant + WP passes for B
        star_b.planets = _apply_gas_giant_disruption(star_b.planets, rng)
        star_b.planets = _apply_wp_collision(star_b.planets, node.warp_points)

        for p in star_b.planets:
            p.moons = _generate_moons(rng, p)

        node.stars.append(star_b)

        if add_trinary:
            star_c = _generate_star(rng, "C")
            star_c.bearing     = _roll(rng, 12)
            star_c.distance_sh = max(1, round((_roll(rng, 4) + 1) * 360 / LM_PER_SH))
            # Component C gets no planets
            node.stars.append(star_c)

    # Re-run coord assignment now that all disruption passes are complete,
    # then expand AST belts exactly once.
    _finalize_coords(node)
    _expand_all_ast_belts(node)

    return node

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

import random
from typing import Optional

from campaign.models import (
    AnomalyType,
    Galaxy,
    GalaxyEdge,
    Moon,
    MoonType,
    Planet,
    PlanetType,
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
    # Fallback: minimum valid pair
    return roll_orbit_distances(1, 3) or (1, 3, 5, 9, 17, 33, 65, 129, 257)


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
# Public entry point
# ---------------------------------------------------------------------------

def generate_system(
    rng: random.Random,
    node_id: str,
    category: SystemCategory = SystemCategory.NORMAL,
) -> SystemNode:
    """Generate a complete system node.

    Steps:
      1. Generate primary star (Component A), unless starless.
      2. Optionally generate binary (B) and trinary (C) companions.
      3. Generate planets for A (and B if binary).
      4. Apply binary AST disruption.
      5. Generate warp points.
      6. Apply Gas Giant AST conversion.
      7. Apply WP–planet collision.
      8. Generate moons.

    The caller is responsible for deciding the category and whether to
    add binary/trinary companions.  Use generate_system_full() for an
    all-in-one roll including binary/trinary probability.
    """
    node = SystemNode(node_id=node_id)

    if category == SystemCategory.STARLESS:
        node.warp_points = _generate_warp_points(rng, node_id, "starless")
        return node

    # -- Primary star -------------------------------------------------
    star_a = _generate_star(rng, "A")
    node.stars.append(star_a)

    # -- Planets for A ------------------------------------------------
    star_a.planets = _generate_planets(rng, star_a, "A")

    # -- Determine WP category before binary changes planet list -------
    # (We need to know has_planets for the WP table; check now)
    has_any_planets = bool(star_a.planets)

    # -- WP generation (Step 6) ---------------------------------------
    wp_cat = "without_planets" if not has_any_planets else "with_planets"
    if not star_a.has_planets_possible:
        wp_cat = "without_planets"
    node.warp_points = _generate_warp_points(rng, node_id, wp_cat)

    # -- Gas Giant AST conversion (Step 7) ----------------------------
    star_a.planets = _apply_gas_giant_disruption(star_a.planets, rng)

    # -- WP–planet collision (Step 8) ---------------------------------
    star_a.planets = _apply_wp_collision(star_a.planets, node.warp_points)

    # -- Moons (Step 9) -----------------------------------------------
    for p in star_a.planets:
        p.moons = _generate_moons(rng, p)

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
    """
    node = generate_system(rng, node_id)
    if not node.stars:
        return node

    star_a = node.primary
    if star_a is None:
        return node

    if add_binary:
        star_b = _generate_star(rng, "B")
        star_b.bearing     = _roll(rng, 12)
        star_b.distance_sh = _roll(rng, 12) + _roll(rng, 12) + 5  # 2d12 + 5

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
            star_c.distance_sh = (_roll(rng, 4) + 1) * 30  # (1d4+1) StMPs × 30 sH
            # Component C gets no planets
            node.stars.append(star_c)

    return node

"""Tests for the campaign system generator."""

from __future__ import annotations

import random

import pytest

from campaign.generator import (
    generate_system,
    generate_system_with_companions,
    _apply_binary_disruption,
    _apply_gas_giant_disruption,
    _apply_wp_collision,
)
from campaign.linker import build_galaxy, link_galaxy
from campaign.models import (
    LM_PER_SH,
    Planet,
    PlanetType,
    SpectralClass,
    Star,
    SystemCategory,
    SystemNode,
    WarpPoint,
    WPVisibility,
)


def _lm(lm: int) -> int:
    """Convert a canonical LM distance to sH using the current scale constant."""
    return max(1, round(lm / LM_PER_SH))
from campaign.tables import (
    classify_orbit,
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
# Tables
# ---------------------------------------------------------------------------

class TestSpectralClassTable:
    def test_blue_giant(self):
        sc, is_ano = roll_spectral_class(3)
        assert sc == SpectralClass.BLUE_GIANT
        assert not is_ano

    def test_white(self):
        sc, _ = roll_spectral_class(10)
        assert sc == SpectralClass.WHITE

    def test_yellow(self):
        sc, _ = roll_spectral_class(30)
        assert sc == SpectralClass.YELLOW

    def test_red_dwarf(self):
        sc, _ = roll_spectral_class(90)
        assert sc == SpectralClass.RED_DWARF

    def test_red_giant(self):
        sc, _ = roll_spectral_class(100)
        assert sc == SpectralClass.RED_GIANT

    def test_roll_100_same_as_0(self):
        sc1, _ = roll_spectral_class(100)
        sc2, _ = roll_spectral_class(0)
        assert sc1 == sc2


class TestAnomalyTable:
    def test_blackhole(self):
        assert roll_anomaly_type(1) == roll_anomaly_type(2)

    def test_pulsar(self):
        from campaign.models import AnomalyType
        assert roll_anomaly_type(80) == AnomalyType.PULSAR

    def test_asteroid_cluster(self):
        from campaign.models import AnomalyType
        assert roll_anomaly_type(100) == AnomalyType.ASTEROID_CLUSTER


class TestOrbitDistances:
    def test_valid_pair(self):
        result = roll_orbit_distances(1, 3)
        assert result is not None
        assert result[0] == _lm(12)
        assert result[1] == _lm(36)

    def test_gap_too_small_returns_none(self):
        assert roll_orbit_distances(5, 6) is None
        assert roll_orbit_distances(3, 3) is None

    def test_ordering_normalised(self):
        assert roll_orbit_distances(3, 1) == roll_orbit_distances(1, 3)

    def test_max_pair(self):
        result = roll_orbit_distances(8, 10)
        assert result is not None
        assert result[0] == _lm(96)
        assert result[1] == _lm(120)

    def test_none_slots_present(self):
        result = roll_orbit_distances(1, 6)
        assert result is not None
        assert None in result


class TestClassifyOrbit:
    def test_tidelock(self):
        # Yellow: tidelock 12-36 LM; 24 LM is hot
        assert classify_orbit(SpectralClass.YELLOW, _lm(24)) == "hot"

    def test_lwz(self):
        # Yellow: biosphere 72-144 LM; 108 LM is lwz
        assert classify_orbit(SpectralClass.YELLOW, _lm(108)) == "lwz"

    def test_cold_rocky(self):
        # Yellow: rocky 12-192 LM, bio 72-144, tidelock 12-36; 168 LM is cold_rocky
        assert classify_orbit(SpectralClass.YELLOW, _lm(168)) == "cold_rocky"

    def test_gas(self):
        # Yellow: gas 204-996 LM; 600 LM is gas
        assert classify_orbit(SpectralClass.YELLOW, _lm(600)) == "gas"

    def test_ice(self):
        # Yellow: ice 1008-3600 LM; 1200 LM is ice
        assert classify_orbit(SpectralClass.YELLOW, _lm(1200)) == "ice"

    def test_beyond(self):
        assert classify_orbit(SpectralClass.YELLOW, 9999) == "beyond"

    def test_red_dwarf_no_biosphere(self):
        # Red Dwarf: tidelock 12 LM, rocky 12-36 LM; 12 LM is hot, 24 LM is cold_rocky
        assert classify_orbit(SpectralClass.RED_DWARF, _lm(12)) == "hot"
        assert classify_orbit(SpectralClass.RED_DWARF, _lm(24)) == "cold_rocky"


class TestRollPlanet:
    def test_no_planet(self):
        mass, ptype = roll_planet(1, "lwz")
        assert ptype is None

    def test_ast(self):
        mass, ptype = roll_planet(4, "gas")
        assert ptype == PlanetType.AST

    def test_terran(self):
        mass, ptype = roll_planet(50, "lwz")
        assert ptype == PlanetType.T
        assert mass == 2

    def test_sub_terran(self):
        mass, ptype = roll_planet(80, "lwz")
        assert ptype == PlanetType.ST
        assert mass == 3

    def test_gas_giant(self):
        _, ptype = roll_planet(50, "gas")
        assert ptype == PlanetType.G

    def test_ice_giant(self):
        _, ptype = roll_planet(50, "ice")
        assert ptype == PlanetType.I

    def test_beyond_returns_none(self):
        _, ptype = roll_planet(50, "beyond")
        assert ptype is None


class TestWPCount:
    def test_starless_min(self):
        assert roll_wp_count(1, "starless") == 1

    def test_with_planets_range(self):
        assert roll_wp_count(19, "with_planets") == 1
        assert roll_wp_count(20, "with_planets") == 2

    def test_nexus_uses_d10(self):
        count = roll_wp_count(100, "with_planets", roll10=5)
        assert count == 6

    def test_nexus_max(self):
        count = roll_wp_count(100, "starless", roll10=10)
        assert count == 10


class TestWPDistance:
    def test_min(self):
        assert roll_wp_distance(1) == _lm(12)

    def test_max(self):
        assert roll_wp_distance(100) == _lm(360)

    def test_mid(self):
        assert roll_wp_distance(50) == _lm(240)


class TestWPVisibility:
    def test_open(self):
        assert roll_wp_visibility(4) == WPVisibility.OPEN

    def test_closed_low(self):
        assert roll_wp_visibility(7) == WPVisibility.CLOSED

    def test_closed_mid(self):
        assert roll_wp_visibility(9) == WPVisibility.CLOSED

    def test_closed_high(self):
        assert roll_wp_visibility(10) == WPVisibility.CLOSED


class TestMoonCount:
    def test_gas_giant_modifier(self):
        assert moon_count_modifier(PlanetType.G, 2) == 50

    def test_mass1_rocky_modifier(self):
        mod = moon_count_modifier(PlanetType.B, 1)
        assert mod == -50

    def test_type_h_modifier(self):
        mod = moon_count_modifier(PlanetType.H, 3)
        assert mod == -15

    def test_type_v_modifier(self):
        mod = moon_count_modifier(PlanetType.V, 2)
        assert mod == -10 - 35  # mass 2 rocky + V penalty

    def test_roll_below_1_gives_0_moons(self):
        # Mass 1 H: -50 - 15 = -65; roll 1 → 1 + (-65) = -64 → 0 moons
        assert roll_moon_count(1, PlanetType.H, 1) == 0

    def test_gas_giant_many_moons(self):
        # G planet: +50; roll 55 → 105 → 3 moons
        assert roll_moon_count(55, PlanetType.G, 2) == 3


# ---------------------------------------------------------------------------
# AST disruption passes
# ---------------------------------------------------------------------------

def _make_planet(dist: int, ptype: PlanetType = PlanetType.T) -> Planet:
    return Planet(orbit_slot=1, distance_sh=dist, planet_type=ptype, mass=2)


class TestBinaryDisruption:
    def test_beyond_third_removed(self):
        planets = [_make_planet(10)]
        result = _apply_binary_disruption(planets, separation_sh=9)
        # 10 > 9/3 = 3 → removed
        assert result == []

    def test_between_quarter_and_third_becomes_ast(self):
        planets = [_make_planet(4)]
        result = _apply_binary_disruption(planets, separation_sh=15)
        # 4 > 15/4=3.75 and 4 <= 15/3=5 → AST
        assert len(result) == 1
        assert result[0].planet_type == PlanetType.AST

    def test_within_quarter_unaffected(self):
        planets = [_make_planet(2)]
        result = _apply_binary_disruption(planets, separation_sh=15)
        # 2 <= 15/4=3.75 → unaffected
        assert len(result) == 1
        assert result[0].planet_type == PlanetType.T


class TestGasGiantDisruption:
    def test_20_percent_chance(self):
        # Deterministic: use fixed rng
        rng = random.Random(0)
        hits = 0
        for _ in range(1000):
            planets = [_make_planet(10, PlanetType.G), _make_planet(5)]
            result = _apply_gas_giant_disruption(planets, rng)
            if result[0].planet_type == PlanetType.AST:
                hits += 1
        # Expect ~200 hits; allow generous range
        assert 100 < hits < 350

    def test_already_ast_does_not_roll(self):
        rng = random.Random(42)
        # G planet that was already an AST shouldn't trigger the roll
        planets = [
            _make_planet(20, PlanetType.AST),  # outer, already AST
            _make_planet(10, PlanetType.T),
        ]
        for _ in range(100):
            result = _apply_gas_giant_disruption(list(planets), rng)
            # Inner planet should never be affected
            assert all(p.planet_type == PlanetType.T for p in result
                       if p.distance_sh == 10)

    def test_outermost_first(self):
        rng = random.Random(1)
        # Two G planets; inner G should not convert the T if outer G rolls
        planets = [
            _make_planet(30, PlanetType.G),
            _make_planet(20, PlanetType.G),
            _make_planet(10, PlanetType.T),
        ]
        # After outer G → G at 20 may become AST → G at 20 (if converted) doesn't roll
        result = _apply_gas_giant_disruption(planets, rng)
        assert len(result) == 3


class TestWPCollision:
    def test_planet_at_wp_distance_becomes_ast(self):
        planets = [_make_planet(15)]
        wps = [WarpPoint("W1", bearing=1, distance_sh=15, visibility=WPVisibility.OPEN)]
        result = _apply_wp_collision(planets, wps)
        assert result[0].planet_type == PlanetType.AST

    def test_planet_at_different_distance_unaffected(self):
        planets = [_make_planet(15)]
        wps = [WarpPoint("W1", bearing=1, distance_sh=20, visibility=WPVisibility.OPEN)]
        result = _apply_wp_collision(planets, wps)
        assert result[0].planet_type == PlanetType.T

    def test_already_ast_stays_ast(self):
        planets = [_make_planet(15, PlanetType.AST)]
        wps = [WarpPoint("W1", bearing=1, distance_sh=15, visibility=WPVisibility.OPEN)]
        result = _apply_wp_collision(planets, wps)
        assert result[0].planet_type == PlanetType.AST


# ---------------------------------------------------------------------------
# Generator integration
# ---------------------------------------------------------------------------

class TestGenerateSystem:
    def test_starless_has_no_stars(self):
        rng = random.Random(1)
        node = generate_system(rng, "X-001", SystemCategory.STARLESS)
        assert len(node.stars) == 0
        assert len(node.warp_points) >= 1

    def test_normal_has_primary_star(self):
        rng = random.Random(7)
        node = generate_system(rng, "X-002")
        assert node.primary is not None

    def test_all_planet_distances_positive(self):
        for seed in range(20):
            rng = random.Random(seed)
            node = generate_system(rng, f"S-{seed}")
            for star in node.stars:
                for p in star.planets:
                    assert p.distance_sh > 0

    def test_hi_only_on_t_st_planets(self):
        for seed in range(30):
            rng = random.Random(seed)
            node = generate_system(rng, f"S-{seed}")
            for star in node.stars:
                for p in star.planets:
                    if p.hi is not None:
                        assert p.planet_type in {PlanetType.T, PlanetType.ST}

    def test_no_moons_on_ast(self):
        for seed in range(30):
            rng = random.Random(seed)
            node = generate_system(rng, f"S-{seed}")
            for star in node.stars:
                for p in star.planets:
                    if p.planet_type == PlanetType.AST:
                        assert p.moons == []

    def test_moon_types_match_parent(self):
        for seed in range(30):
            rng = random.Random(seed)
            node = generate_system(rng, f"S-{seed}")
            for star in node.stars:
                for p in star.planets:
                    for m in p.moons:
                        if p.planet_type in {PlanetType.H, PlanetType.V}:
                            from campaign.models import MoonType
                            assert m.moon_type == MoonType.mH
                        elif p.planet_type in {PlanetType.F, PlanetType.I}:
                            from campaign.models import MoonType
                            assert m.moon_type == MoonType.mF

    def test_with_companions(self):
        rng = random.Random(99)
        node = generate_system_with_companions(rng, "BIN-001", add_binary=True)
        components = {s.component for s in node.stars}
        assert "A" in components
        assert "B" in components

    def test_trinary_has_three_stars(self):
        rng = random.Random(123)
        node = generate_system_with_companions(
            rng, "TRI-001", add_binary=True, add_trinary=True
        )
        assert len(node.stars) == 3

    def test_component_c_has_no_planets(self):
        for seed in range(5):
            rng = random.Random(seed)
            node = generate_system_with_companions(
                rng, f"TRI-{seed}", add_binary=True, add_trinary=True
            )
            for star in node.stars:
                if star.component == "C":
                    assert star.planets == []


# ---------------------------------------------------------------------------
# Linker
# ---------------------------------------------------------------------------

class TestLinker:
    def _make_systems(self, n_systems: int, wps_each: int, rng: random.Random) -> dict:
        systems = {}
        for i in range(n_systems):
            sid = f"SYS-{i}"
            wps = [
                WarpPoint(f"{sid}-WP{j}", bearing=1, distance_sh=10 + j,
                          visibility=WPVisibility.OPEN)
                for j in range(wps_each)
            ]
            systems[sid] = SystemNode(node_id=sid, warp_points=wps)
        return systems

    def test_all_wps_linked_or_removed(self):
        rng = random.Random(7)
        systems = self._make_systems(5, 3, rng)
        edges = link_galaxy(systems, rng)
        linked = {wp.wp_id for node in systems.values() for wp in node.warp_points
                  if wp.linked_to is not None}
        all_wps = {wp.wp_id for node in systems.values() for wp in node.warp_points}
        # Every remaining WP must be linked
        assert linked == all_wps

    def test_no_self_links(self):
        rng = random.Random(42)
        systems = self._make_systems(4, 4, rng)
        edges = link_galaxy(systems, rng)
        for edge in edges:
            assert edge.system_a != edge.system_b

    def test_edges_are_symmetric(self):
        rng = random.Random(13)
        systems = self._make_systems(6, 2, rng)
        edges = link_galaxy(systems, rng)
        pairs = {(e.system_a, e.wp_a, e.system_b, e.wp_b) for e in edges}
        for edge in edges:
            wp_b = next(
                wp for node in systems.values() for wp in node.warp_points
                if wp.wp_id == edge.wp_b
            )
            assert wp_b.linked_to == (edge.system_a, edge.wp_a)

    def test_odd_wp_removed(self):
        rng = random.Random(5)
        # 3 systems × 1 WP = 3 WPs; one must be removed
        systems = self._make_systems(3, 1, rng)
        link_galaxy(systems, rng)
        total_remaining = sum(len(n.warp_points) for n in systems.values())
        # At most 2 remain (1 gets removed)
        assert total_remaining <= 2

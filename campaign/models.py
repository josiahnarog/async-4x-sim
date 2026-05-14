"""Dataclasses for the campaign / strategic layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Unit constants
# ---------------------------------------------------------------------------

TH_PER_SH:           int = 2_880  # tactical hexes per strategic hex
LM_PER_SH:           int = 6      # light-minutes per strategic hex
SH_PER_STMP:         int = 30     # strategic hexes per strategic movement point
LM_PER_SPEED_PER_DAY: int = 12    # LM a speed-1 ship travels in one day
                                   # sH/day = speed * LM_PER_SPEED_PER_DAY / LM_PER_SH


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class SpectralClass(str, Enum):
    WHITE        = "White"
    YELLOW_WHITE = "Yellow-White"
    YELLOW       = "Yellow"
    ORANGE       = "Orange"
    RED          = "Red"
    RED_DWARF    = "Red Dwarf"
    # Stars with no planets possible
    BLUE_GIANT   = "Blue Giant"
    WHITE_DWARF  = "White Dwarf"
    RED_GIANT    = "Red Giant"


class AnomalyType(str, Enum):
    BLACKHOLE              = "Blackhole"
    MAGNETAR               = "Magnetar"
    QUATERNARY_SYSTEM      = "Quaternary System"
    LONG_DISTANCE_COMPANION = "Long-Distance Companion"
    PROTO_DISK             = "Proto-Disk Formation"
    GRAVITY_WAVE           = "Gravity Wave Effects"
    PULSAR                 = "Pulsar"
    ASTEROID_CLUSTER       = "Asteroid Cluster"


class PlanetType(str, Enum):
    F   = "F"    # Frozen — no atmosphere, frozen noble gases
    B   = "B"    # Barren cold rocky
    H   = "H"    # Hot rocky
    V   = "V"    # Venus-like — dense poisonous atmosphere
    T   = "T"    # Terran — habitable
    ST  = "ST"   # Sub-Terran — high gravity, dense atmosphere
    G   = "G"    # Gas giant (Jupiter/Saturn analogue)
    I   = "I"    # Ice giant (Neptune/Uranus analogue)
    AST = "AST"  # Asteroid belt


class MoonType(str, Enum):
    mH = "mH"   # for H and V parent planets
    mF = "mF"   # for F and I parent planets
    mB = "mB"   # for all other parent planets (B, T, ST, G)


class WPVisibility(str, Enum):
    OPEN   = "Open"
    CLOSED = "Closed"


class SystemCategory(str, Enum):
    """Broad node category, determines which generation branches are taken."""
    NORMAL         = "Normal"        # Star with planets possible
    NO_PLANET_STAR = "No Planet Star" # Blue Giant, White/Red Dwarf, etc.
    ANOMALY        = "Anomaly"       # Blackhole, Pulsar, etc.
    STARLESS       = "Starless"      # No star; warp points only


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Population:
    owner:    str  # player/faction ID, e.g. "human", "npc_1"
    size:     int  # 1–10
    industry: int  # 1–10


@dataclass
class Moon:
    moon_type: MoonType
    orbit_th:  int        # distance from planet centre in tactical hexes
    is_big:    bool = False
    hi:        Optional[int] = None  # 1–10; revealed after survey; big moons only
    # Tactical hex position (relative to parent planet at TH (0,0))
    q_th:      int   = 0
    r_th:      int   = 0
    # Orbital mechanics
    orbital_angle_0:    float = 0.0   # compass degrees at t=0
    orbital_period_days: float = 0.0  # orbital period in Earth days


@dataclass
class Planet:
    orbit_slot:     int          # 1 (I) through 9 (IX)
    distance_sh:    int          # distance from parent star in sH
    planet_type:    PlanetType
    mass:           Optional[int] = None   # 1, 2, or 3; None for AST
    has_atmosphere: bool = False           # True for Mass 2/3 B and H worlds
    tidelock:       bool = False           # within tidelock zone of parent star
    hi:             Optional[int] = None        # 1–10; revealed after survey; T/ST only
    moons:          list[Moon] = field(default_factory=list)
    population:     Optional[Population] = None
    parent_star:    str = "A"                   # "A" or "B"
    # Strategic hex position (absolute, relative to system primary at sH (0,0))
    q_sh:           int   = 0
    r_sh:           int   = 0
    # Tactical hex position within the planet's sH hex (planet always at TH centre)
    q_th:           int   = 0
    r_th:           int   = 0
    # Orbital mechanics (orbit around parent star)
    orbital_angle_0:    float = 0.0   # compass degrees at t=0
    orbital_period_years: float = 0.0 # orbital period in Earth years


@dataclass
class WarpPoint:
    wp_id:       str
    bearing:     int           # 1–12 sector (each sector = 30°) from primary star
    distance_sh: int           # from primary star in sH
    visibility:  WPVisibility
    linked_to:   Optional[tuple[str, str]] = None  # (system_id, wp_id)
    # Strategic hex position (fixed relative to primary; WPs do not orbit)
    q_sh:        int = 0
    r_sh:        int = 0


@dataclass
class Star:
    component:     str                     # "A", "B", or "C"
    spectral_class: Optional[SpectralClass] = None
    anomaly_type:  Optional[AnomalyType]   = None
    bearing:       Optional[int]           = None  # 1–12; None for primary A
    distance_sh:   int                     = 0     # 0 for primary A
    planets:       list[Planet]            = field(default_factory=list)
    # Strategic hex position (A is always (0,0); B/C computed from bearing+distance)
    q_sh:          int   = 0
    r_sh:          int   = 0
    # Orbital mechanics (B/C orbit around A; A is stationary)
    orbital_angle_0:     float = 0.0   # compass degrees at t=0
    orbital_period_years: float = 0.0  # orbital period in Earth years

    @property
    def has_planets_possible(self) -> bool:
        """False for no-planet star types and anomalies."""
        if self.anomaly_type is not None:
            return False
        no_planet = {SpectralClass.BLUE_GIANT, SpectralClass.WHITE_DWARF,
                     SpectralClass.RED_GIANT}
        return self.spectral_class not in no_planet


@dataclass
class SystemNode:
    node_id:     str
    stars:       list[Star]         = field(default_factory=list)
    warp_points: list[WarpPoint]    = field(default_factory=list)
    ships:       list[CampaignShip] = field(default_factory=list)

    @property
    def primary(self) -> Optional[Star]:
        for s in self.stars:
            if s.component == "A":
                return s
        return None

    @property
    def is_starless(self) -> bool:
        return len(self.stars) == 0

    @property
    def has_planets(self) -> bool:
        return any(s.planets for s in self.stars)

    @property
    def wp_category(self) -> str:
        """Key for WP quantity table lookup."""
        if self.is_starless:
            return "starless"
        if self.has_planets:
            return "with_planets"
        return "without_planets"


@dataclass
class CampaignShip:
    ship_id:   str
    name:      str
    hull_type: str            # "DD", "FG", etc.
    speed:     int            # tactical speed rating
    system_id: str            # node_id of the system the ship is currently in
    q_sh:      int            # position when order_day was set
    r_sh:      int
    order_day: float = 0.0    # tDays at which the current move order was issued
    dest_q:    Optional[int] = None
    dest_r:    Optional[int] = None

    @property
    def sH_per_day(self) -> float:
        """Movement rate in sH/day derived from speed rating and current scale."""
        return self.speed * LM_PER_SPEED_PER_DAY / LM_PER_SH


@dataclass
class GalaxyEdge:
    """A warp-point link between two systems."""
    system_a: str
    wp_a:     str
    system_b: str
    wp_b:     str


@dataclass
class Galaxy:
    systems: dict[str, SystemNode] = field(default_factory=dict)
    edges:   list[GalaxyEdge]      = field(default_factory=list)

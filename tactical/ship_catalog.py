"""Ship design catalog: hull types and system definitions.

This module contains the static data used by the ship designer.
It is intentionally separate from hull_types.py (which holds tactical-engine
HullType objects for the four currently playable hulls) so new hull types can
be catalogued here before they are given full tactical implementations.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Optional


# ---------------------------------------------------------------------------
# System catalog
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SystemEntry:
    code: str         # e.g. "L"
    name: str         # e.g. "Laser"
    cost: int         # build cost in credits
    hull_spaces: int  # hull spaces consumed
    ls_capacity: int = 0  # life-support HS covered per unit (0 = not a LS system)


# Systems available in the ship designer.
# "Bf" (Fighter Bay) is shown here; the tactical engine uses "Bh" for the same
# system — the builder maps Bf → Bh when generating system strings.
SYSTEMS: list[SystemEntry] = [
    SystemEntry("S",  "Shield",              cost=4,   hull_spaces=1),
    SystemEntry("A",  "Armor",               cost=2,   hull_spaces=1),
    SystemEntry("Q",  "Crew Quarters",       cost=10,  hull_spaces=1, ls_capacity=15),
    SystemEntry("I",  "Military Engine",     cost=20,  hull_spaces=1),
    SystemEntry("Y",  "Military Sensors",    cost=20,  hull_spaces=1),
    SystemEntry("X",  "Survey Sensors",      cost=30,  hull_spaces=1),
    SystemEntry("G",  "Gun",                 cost=20,  hull_spaces=2),
    SystemEntry("D",  "Point Defence",       cost=15,  hull_spaces=2),
    SystemEntry("L",  "Laser",               cost=27,  hull_spaces=4),
    SystemEntry("N",  "Needle Beam",         cost=35,  hull_spaces=4),
    SystemEntry("R",  "Standard Missile",    cost=30,  hull_spaces=4),
    SystemEntry("F",  "Force Beam",          cost=30,  hull_spaces=5),
    SystemEntry("E",  "Energy Beam",         cost=35,  hull_spaces=6),
    SystemEntry("K",  "Rail Gun (Kinetic)",  cost=45,  hull_spaces=7),
    SystemEntry("Bl", "Launch Bay",          cost=60,  hull_spaces=3),
    SystemEntry("Bh", "Hangar Bay",          cost=60,  hull_spaces=6),
    SystemEntry("Mg", "Magazine",            cost=10,  hull_spaces=1),
]

SYSTEMS_BY_CODE: dict[str, SystemEntry] = {s.code: s for s in SYSTEMS}


def system_hull_spaces(token: str) -> int:
    """Hull spaces occupied by one system with the given token (e.g. 'Bh', 'L', 'Mg').

    Returns 0 for unknown tokens so callers can sum safely without special-casing.
    """
    entry = SYSTEMS_BY_CODE.get(token)
    return entry.hull_spaces if entry is not None else 0


# ---------------------------------------------------------------------------
# Hull type catalog
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HullEntry:
    designation: str    # e.g. "FG"
    name: str           # e.g. "Frigate"
    tier: int           # 0–19 numeric class index
    req_el: int         # required engineering level to build
    hs_min: int         # minimum hull spaces
    hs_max: int         # maximum hull spaces
    cost_per_hs: float  # base hull cost per hull space
    epr_i: str          # I-engine power ratio (EPR) as fraction string, e.g. "2/3"
    ia: str             # initiative/agility rating string, e.g. "5(2)"
    # Design requirements
    req_min_speed: int = 1    # minimum designed MP; set to 0 for stations / immobile hulls
    # Tactical engine attributes — populated for hulls with a full implementation.
    max_speed: Optional[int] = None
    turn_cost: Optional[int] = None


HULL_CATALOG: list[HullEntry] = [
    HullEntry("EX", "Escort",            tier=0,  req_el=1,  hs_min=5,    hs_max=7,    cost_per_hs=3.50, epr_i="1/4",  ia="6(2-)",  max_speed=6, turn_cost=2),
    HullEntry("ES", "Escort Scout",      tier=1,  req_el=1,  hs_min=8,    hs_max=12,   cost_per_hs=3.85, epr_i="1/3",  ia="6(2)",   max_speed=6, turn_cost=2),
    HullEntry("CT", "Corvette",          tier=2,  req_el=1,  hs_min=13,   hs_max=16,   cost_per_hs=4.20, epr_i="1/2",  ia="6(2)",   max_speed=6, turn_cost=2),
    HullEntry("FG", "Frigate",           tier=3,  req_el=1,  hs_min=17,   hs_max=22,   cost_per_hs=4.55, epr_i="2/3",  ia="5(2)",   max_speed=5, turn_cost=2),
    HullEntry("DD", "Destroyer",         tier=4,  req_el=1,  hs_min=23,   hs_max=30,   cost_per_hs=4.90, epr_i="1",    ia="5(3-)",  max_speed=5, turn_cost=3),
    HullEntry("CL", "Light Cruiser",     tier=5,  req_el=2,  hs_min=31,   hs_max=45,   cost_per_hs=5.25, epr_i="3/2",  ia="4(3)",   max_speed=4, turn_cost=3),
    HullEntry("CA", "Heavy Cruiser",     tier=6,  req_el=3,  hs_min=46,   hs_max=60,   cost_per_hs=5.60, epr_i="2",    ia="4(3)",   max_speed=4, turn_cost=3),
    HullEntry("BC", "Battle Cruiser",    tier=7,  req_el=5,  hs_min=61,   hs_max=80,   cost_per_hs=5.95, epr_i="5/2",  ia="4(4-)",  max_speed=4, turn_cost=4),
    HullEntry("BB", "Battleship",        tier=8,  req_el=6,  hs_min=81,   hs_max=100,  cost_per_hs=6.30, epr_i="3",    ia="3(4)",   max_speed=3, turn_cost=4),
    HullEntry("DN", "Dreadnought",       tier=9,  req_el=7,  hs_min=101,  hs_max=130,  cost_per_hs=6.65, epr_i="4",    ia="3(4)",   max_speed=3, turn_cost=4),
    HullEntry("SD", "Superdreadnought",  tier=10, req_el=9,  hs_min=131,  hs_max=165,  cost_per_hs=7.00, epr_i="5",    ia="3(5-)",  max_speed=3, turn_cost=5),
    HullEntry("MT", "Monitor",           tier=11, req_el=11, hs_min=166,  hs_max=200,  cost_per_hs=7.35, epr_i="6",    ia="2(5)",   max_speed=2, turn_cost=5),
    HullEntry("HM", "Heavy Monitor",     tier=12, req_el=13, hs_min=201,  hs_max=250,  cost_per_hs=7.70, epr_i="15/2", ia="2(5)",   max_speed=2, turn_cost=5),
    HullEntry("SM", "Super Monitor",     tier=13, req_el=15, hs_min=251,  hs_max=350,  cost_per_hs=8.05, epr_i="9",    ia="2(6-)",  max_speed=2, turn_cost=6),
    HullEntry("LN", "Line Ship",         tier=14, req_el=18, hs_min=351,  hs_max=500,  cost_per_hs=8.40, epr_i="10",   ia="1(6)",   max_speed=1, turn_cost=6),
    HullEntry("JG", "Juggernaut",        tier=15, req_el=22, hs_min=501,  hs_max=750,  cost_per_hs=8.50, epr_i="14",   ia="1(6)",   max_speed=1, turn_cost=6),
    HullEntry("MM", "Mammoth",           tier=16, req_el=27, hs_min=751,  hs_max=1000, cost_per_hs=8.50, epr_i="20",   ia="1(7-)",  max_speed=1, turn_cost=7),
    HullEntry("CO", "Colossus",          tier=17, req_el=33, hs_min=1001, hs_max=1300, cost_per_hs=8.50, epr_i="30",   ia="0(7)",   req_min_speed=0, max_speed=0, turn_cost=7),
    HullEntry("GN", "Giant",             tier=18, req_el=40, hs_min=1301, hs_max=1600, cost_per_hs=8.50, epr_i="35",   ia="0(7)",   req_min_speed=0, max_speed=0, turn_cost=7),
    HullEntry("TN", "Titan",             tier=19, req_el=48, hs_min=1601, hs_max=2000, cost_per_hs=8.50, epr_i="40",   ia="0(8-)",  req_min_speed=0, max_speed=0, turn_cost=8),
]

HULL_BY_DESIGNATION: dict[str, HullEntry] = {h.designation: h for h in HULL_CATALOG}


def hull_engines_per_room(hull: HullEntry) -> int:
    """Return the standard number of engine systems placed in one engine room.

    Rules:
      EPR ≤ 1  → 1 engine per room (each room yields floor(1/EPR) MP)
      EPR > 1  → EPR engines per room (each room yields 1 MP)
                 For non-integer EPR the *last* room gets ceil(EPR) engines;
                 this function returns floor(EPR) as the standard room size.
    """
    epr = Fraction(hull.epr_i)
    if epr <= 1:
        return 1
    return int(epr)  # floor for non-integer EPR > 1


def hull_base_cost(hull: HullEntry, hull_spaces: int) -> float:
    """Total base hull cost for a given size."""
    return hull.cost_per_hs * hull_spaces


def systems_cost(system_codes: list[str]) -> int:
    """Sum of build costs for a list of system codes (engine groups flattened to I)."""
    total = 0
    for code in system_codes:
        entry = SYSTEMS_BY_CODE.get(code)
        if entry:
            total += entry.cost
    return total


def systems_hull_spaces(system_codes: list[str]) -> int:
    """Sum of hull spaces consumed by a list of system codes."""
    total = 0
    for code in system_codes:
        entry = SYSTEMS_BY_CODE.get(code)
        if entry:
            total += entry.hull_spaces
    return total


# ---------------------------------------------------------------------------
# System string codec
# ---------------------------------------------------------------------------
_BUILDER_TO_TACTICAL: dict[str, str] = {}
_TACTICAL_TO_BUILDER: dict[str, str] = {}


def track_to_system_string(track: list[dict]) -> str:
    """Convert a designer track (list of slot dicts) to a compact system string.

    Each slot is one of:
      {"type": "system",       "code": "S"}
      {"type": "engine_room",  "count": 3}   → "(III)"
    """
    parts = []
    for slot in track:
        if slot["type"] == "engine_room":
            n = max(1, int(slot.get("count", 1)))
            parts.append(f"({'I' * n})")
        elif slot["type"] == "shield_room":
            n = int(slot.get("count", 0))
            if n > 0:
                parts.append("S" * n)
        elif slot["type"] == "armor_room":
            n = int(slot.get("count", 0))
            if n > 0:
                parts.append("A" * n)
        else:
            code = slot["code"]
            tactical_code = _BUILDER_TO_TACTICAL.get(code, code)
            parts.append(tactical_code)
    return "".join(parts)


def system_string_to_track(sys_str: str) -> list[dict]:
    """Parse a tactical system string back to a designer track.

    Inverse of track_to_system_string — used when loading a saved design.
    """
    track: list[dict] = []
    i = 0
    while i < len(sys_str):
        if sys_str[i] == "(":
            j = sys_str.index(")", i)
            group = sys_str[i + 1:j]
            count = group.count("I")
            track.append({"type": "engine_room", "count": count})
            i = j + 1
        else:
            # Greedy: try two-char token first (Bh, Bl, Mg, …)
            two = sys_str[i:i + 2]
            code = _TACTICAL_TO_BUILDER.get(two, two)
            if len(two) == 2 and two[1].islower():
                track.append({"type": "system", "code": code})
                i += 2
            else:
                one = sys_str[i]
                track.append({"type": "system", "code": one})
                i += 1
    return track

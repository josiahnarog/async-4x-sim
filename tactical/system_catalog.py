"""Ship system catalog — authoritative descriptions for all system codes.

Each entry describes one system type as it appears on a ship's system track.
This catalog is the source of truth for user-facing documentation and UI
tooltips; mechanical behaviour is implemented in ship_systems.py and combat.py.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SystemEntry:
    code: str
    name: str
    category: str   # "defense" | "weapon" | "propulsion" | "utility" | "carrier"
    description: str


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

SYSTEM_CATALOG: dict[str, SystemEntry] = {entry.code: entry for entry in [

    # --- Defense -----------------------------------------------------------

    SystemEntry(
        code="S",
        name="Shield",
        category="defense",
        description=(
            "Energy shielding that absorbs incoming damage before armor is "
            "reached. Certain weapons — notably the Laser — bypass shields "
            "entirely. Shields regenerate between combats; advanced shield "
            "systems may eventually regenerate during tactical engagements."
        ),
    ),

    SystemEntry(
        code="A",
        name="Armor",
        category="defense",
        description=(
            "Structural plating that absorbs damage after shields. Some "
            "weapons, such as the Electron Beam, bypass armor and strike "
            "internal systems directly."
        ),
    ),

    SystemEntry(
        code="D",
        name="Point Defense",
        category="defense",
        description=(
            "Short-range autocannons that intercept incoming missiles and "
            "engage attacking fighter squadrons. Each mount fires three shots "
            "per incoming volley. Point defense is suppressed when the "
            "attacker approaches from directly astern."
        ),
    ),

    # --- Weapons -----------------------------------------------------------

    SystemEntry(
        code="L",
        name="Laser",
        category="weapon",
        description=(
            "Directed-energy weapon that bypasses shields, damaging armor and "
            "internal systems directly. Effective at short-to-medium range."
        ),
    ),

    SystemEntry(
        code="E",
        name="Electron Beam",
        category="weapon",
        description=(
            "High-energy particle weapon that bypasses armor entirely, "
            "striking internal systems directly. Deals half damage against "
            "shields."
        ),
    ),

    SystemEntry(
        code="F",
        name="Force Beam",
        category="weapon",
        description=(
            "Kinetic energy projector with no special bypass rules. Damage "
            "is applied to systems in order, starting from the outermost "
            "intact layer."
        ),
    ),

    SystemEntry(
        code="R",
        name="Standard Missile Launcher",
        category="weapon",
        description=(
            "Carries ten internal rounds; draws from ship magazines (Mg) "
            "first. All active launchers fire together as a single volley. "
            "Incoming missiles may be intercepted by point defense."
        ),
    ),

    SystemEntry(
        code="Mg",
        name="Magazine",
        category="weapon",
        description=(
            "Ammunition storage holding fifty rounds shared across all "
            "missile launchers. The leftmost active magazine is drained "
            "first. Destroying a magazine does not cause an explosion."
        ),
    ),

    SystemEntry(
        code="G",
        name="Gun / Autocannon",
        category="weapon",
        description=(
            "Fighter-scale weapons incapable of targeting capital ships. "
            "Highly effective against fighter squadrons."
        ),
    ),

    # --- Propulsion --------------------------------------------------------

    SystemEntry(
        code="I",
        name="Engine Room",
        category="propulsion",
        description=(
            "Internal drive systems grouped into engine rooms. If any system "
            "within a room is destroyed, the entire room goes offline and "
            "contributes no thrust. Ungrouped engine systems are lost "
            "individually."
        ),
    ),

    # --- Utility -----------------------------------------------------------

    SystemEntry(
        code="Q",
        name="Crew Quarters",
        category="utility",
        description=(
            "Crew living spaces and life support systems. Every ship requires "
            "at least one; larger vessels may carry several. If all crew "
            "quarters are destroyed the crew must operate in vacuum suits, "
            "imposing a \u22122 penalty to all weapon fire."
        ),
    ),

    SystemEntry(
        code="Y",
        name="Sensors",
        category="utility",
        description=(
            "Active and passive sensor suite. Provides the ship with "
            "detection capability, allowing it to identify enemy contacts at "
            "greater range or in more detail. More advanced sensor systems "
            "extend detection range and improve contact resolution."
        ),
    ),

    SystemEntry(
        code="Clk",
        name="Cloaking Device",
        category="utility",
        description=(
            "Stealth system that reduces the ship\u2019s detectability to "
            "enemy sensors. \u2014 In development."
        ),
    ),

    # --- Carrier -----------------------------------------------------------

    SystemEntry(
        code="Bh",
        name="Hangar Bay",
        category="carrier",
        description=(
            "Pressurised bay that stores, refuels, and rearms one fighter "
            "squadron. A squadron must be docked in an active hangar bay to "
            "recover from a sortie or receive replenishment."
        ),
    ),

    SystemEntry(
        code="Bl",
        name="Launch Bay",
        category="carrier",
        description=(
            "Catapult and recovery equipment. Each active launch bay permits "
            "one squadron launch or recovery operation per turn."
        ),
    ),
]}

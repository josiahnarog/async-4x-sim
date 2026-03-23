"""Fighter combat event dataclasses.

Pure data types — no game logic.  Imported by resolution modules, the web
layer, and the REPL.  Keeping them separate from the resolution code means
consumers that only need isinstance checks don't pull in the full combat graph.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from sim.hexgrid import Hex
from tactical.battle_state import ShipID
from tactical.events import UnitDestroyedEvent
from tactical.squadron_state import SquadronID
from tactical.weapons import WeaponType


@dataclass(frozen=True, slots=True)
class FighterShotEvent:
    """One fighter's single weapon shot in a dogfight or attack run."""
    weapon:  WeaponType
    roll:    int
    to_hit:  int    # final adjusted target number
    hit:     bool
    damage:  int    # casualties vs squadron; system-hit damage vs ship


@dataclass(frozen=True, slots=True)
class DogfightEvent:
    """One squadron fires all its internal weapons at a target squadron.

    mvr_delta = attacker.effective_mvr - target.effective_mvr; positive means
    the attacker has the maneuverability advantage.
    """
    attacker_id:      SquadronID
    target_id:        SquadronID
    mvr_delta:        int
    shots:            tuple[FighterShotEvent, ...]
    total_casualties: int


@dataclass(frozen=True, slots=True)
class AttackRunEvent:
    """A fighter squadron makes an attack run on a capital ship.

    Two-phase event:
      1. PD fires at the incoming fighters (pd_* fields).
      2. Surviving fighters fire their weapons at the ship (weapon_shots).
    """
    attacker_id:           SquadronID
    target_id:             ShipID
    pd_shots_fired:        int
    pd_hits:               int
    pd_rolls:              tuple[int, ...]
    fighters_killed_by_pd: int
    surviving_strength:    int
    weapon_shots:          tuple[FighterShotEvent, ...]
    total_ship_damage:     int


@dataclass(frozen=True, slots=True)
class BreakOffEvent:
    """A squadron broke off from a dogfight.

    Parting shots are fired by each co-hex enemy before the squadron moves.
    final_pos may differ from dest if the squadron lacked the MP to reach it.
    """
    squadron_id:      SquadronID
    dest:             Hex
    parting_shots:    tuple[DogfightEvent, ...]
    casualties_taken: int
    final_pos:        Hex


# Union of all event types emitted during COMBAT_SMALL.
FighterCombatEvent = Union[
    DogfightEvent,
    AttackRunEvent,
    BreakOffEvent,
    UnitDestroyedEvent,
]

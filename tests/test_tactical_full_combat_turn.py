from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sim.hexgrid import Hex
from tactical.battle_state import BattleState
from tactical.combat import resolve_large_fire
from tactical.facing import Facing
from tactical.ship_state import ShipState
from tactical.ship_systems import ShipSystems
from tactical.weapons import WeaponType


@dataclass
class FixedRNG:
    """
    Deterministic RNG that returns a fixed sequence of d10 rolls.
    """
    rolls: list[int]

    def randint(self, a: int, b: int) -> int:
        assert a == 1 and b == 10, "This FixedRNG only supports d10 rolls"
        if not self.rolls:
            raise AssertionError("FixedRNG ran out of rolls")
        return int(self.rolls.pop(0))


def test_full_turn_missiles_vs_pd_applies_remaining_damage():
    """
    Scenario:
      - A1 fires Standard Missiles from 4 launchers (RRRR) at range 1
      - Missile to-hit at range 1 is 6 (hit on roll <= 6)
      - Two missiles hit; target has 1 PD mount (D) => 3 shots at 3+ (hit on roll <= 3)
      - PD intercepts 1 of the 2 hits => 1 hit remains, which destroys the next intact system
    """

    # Rolls consumed in order:
    #   Missile attack rolls (4 shots): 2(H), 7(M), 6(H), 10(M) => 2 hits
    #   PD rolls (min(hits=2, shots=3)=2 shots): 1(H), 10(M) => 1 intercept
    rng = FixedRNG([2, 7, 6, 10, 1, 10])

    attacker = ShipState(
        ship_id="A1",
        owner_id="A",
        pos=Hex(0, 0),
        facing=Facing.N,
        mp=0,
        turn_cost=3,
        turn_charge=0,
        systems=ShipSystems.parse("RRRR"),
    )

    # Target systems: put PD later so damage hits shields first (more intuitive)
    # Order: S S A H D D
    target = ShipState(
        ship_id="B1",
        owner_id="B",
        pos=Hex(0, 1),  # range 1
        facing=Facing.S,
        mp=0,
        turn_cost=3,
        turn_charge=0,
        systems=ShipSystems.parse("SSAHDD"),
    )

    b0 = BattleState(ships={"A1": attacker, "B1": target})

    print("PD:", target.systems.point_defense())

    b1, ev = resolve_large_fire(
        b0,
        attacker_id="A1",
        target_id="B1",
        weapon=WeaponType.STANDARD_MISSILE,
        rng=rng,
    )

    print("ev:", ev)

    # Verify volley math
    assert ev.missile_hits == 2
    assert ev.pd_intercepted == 1
    assert ev.remaining_hits == 1
    assert ev.raw_damage == 1

    # One remaining hit destroys the first intact system: first shield
    assert b1.ships["B1"].systems.render_compact() == "!SSAHDD"

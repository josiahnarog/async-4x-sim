# sim/unit_types.py

from sim.units import UnitType

SCOUT = UnitType(
    name="Scout",
    max_groups=6,
    movement=1,
    is_combatant=True,
    initiative="E",
    attack=3,
    defense=0,
    hull=1,
)

BATTLESHIP = UnitType(
    name="Battleship",
    max_groups=6,
    movement=1,
    is_combatant=True,
    initiative="A",
    attack=5,
    defense=2,
    hull=3,
)

RAIDER = UnitType(
    name="Raider",
    max_groups=6,
    movement=1,
    is_combatant=True,
    initiative="D",
    attack=4,
    defense=0,
    hull=2,
    builtin_cloak=1,
)

DECOY = UnitType(
    name="Decoy",
    max_groups=6,
    movement=1,
    is_combatant=False,
    initiative="E",
    attack=0,
    defense=0,
    hull=1,
)

COLONY_SHIP = UnitType(
    name="Colony Ship",
    max_groups=99,
    movement=1,
    is_combatant=False,
    initiative="E",
    attack=0,
    defense=0,
    hull=1,
)
COLONY_SHIP.can_colonize = True

MINING_SHIP = UnitType(
    name="Mining Ship",
    max_groups=99,
    movement=1,
    is_combatant=False,
    initiative="E",
    attack=0,
    defense=0,
    hull=1,
)
MINING_SHIP.can_mine = True


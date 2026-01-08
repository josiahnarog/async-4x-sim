# sim/units.py
from sim.hexgrid import Hex


class PlayerID:
    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return self.name

    def __eq__(self, other):
        return isinstance(other, PlayerID) and self.name == other.name

    def __hash__(self):
        return hash(self.name)


class UnitType:
    def __init__(self, name, max_groups, movement,
                 is_combatant: bool = True,
                 initiative: str = "C",
                 attack: int = 0,
                 defense: int = 0,
                 hull: int = 1,
                 builtin_cloak: int = 0,
                 builtin_sensors: int = 0,
                 can_colonize: bool = False,
                 can_mine: bool = False):
        self.name = name
        self.max_groups = max_groups
        self.movement = movement
        self.is_combatant = is_combatant

        self.initiative = initiative
        self.attack = attack
        self.defense = defense
        self.hull = hull

        self.builtin_cloak = builtin_cloak
        self.builtin_sensors = builtin_sensors
        self.can_colonize = can_colonize
        self.can_mine = can_mine
        self.cargo_minerals = 0


class UnitGroup:
    def __init__(self, group_id: str, owner: PlayerID, unit_type: UnitType,
                 count: int, location,
                 tactics: int = 0, cloak_bonus: int = 0, sensors_bonus: int = 0,
                 attack_bonus: int = 0, defense_bonus: int = 0):
        self.group_id = group_id
        self.owner = owner
        self.unit_type = unit_type
        self.count = count
        self.location = location if isinstance(location, Hex) else Hex(*location)

        self.tactics = int(tactics)
        self.cloak_bonus = int(cloak_bonus)
        self.sensors_bonus = int(sensors_bonus)
        self.attack_bonus = int(attack_bonus)
        self.defense_bonus = int(defense_bonus)
        self.damage = 0

    @property
    def initiative(self) -> str:
        return self.unit_type.initiative

    @property
    def attack(self) -> int:
        return int(self.unit_type.attack) + self.attack_bonus

    @property
    def defense(self) -> int:
        return int(self.unit_type.defense) + self.defense_bonus

    @property
    def hull(self) -> int:
        return max(1, int(self.unit_type.hull))

    @property
    def cloak_level(self) -> int:
        return int(self.unit_type.builtin_cloak) + self.cloak_bonus

    @property
    def sensor_level(self) -> int:
        return int(self.unit_type.builtin_sensors) + self.sensors_bonus

    @property
    def movement(self) -> int:
        return int(self.unit_type.movement)

    def __repr__(self):
        return f"{self.group_id}({self.owner}) at {self.location}"



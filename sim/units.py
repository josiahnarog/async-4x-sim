# sim/units.py

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
    def __init__(self, name: str, max_groups: int, movement: int = 3):
        self.name = name
        self.max_groups = max_groups
        self.movement = movement


class UnitGroup:
    def __init__(self, group_id: str, owner: PlayerID, unit_type: UnitType, count: int, tech_level: int, location):
        self.group_id = group_id
        self.owner = owner
        self.unit_type = unit_type
        self.count = count
        self.tech_level = tech_level
        self.location = location

    @property
    def movement(self) -> int:
        return self.unit_type.movement

    def __repr__(self):
        return f"{self.group_id}({self.owner}) at {self.location}"


# sim/units.py

class PlayerID:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name


class UnitType:
    def __init__(self, name, max_groups, movement=3):
        self.name = name
        self.max_groups = max_groups
        self.movement = movement


class UnitGroup:
    def __init__(self, group_id, owner, unit_type, count, tech_level, location):
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

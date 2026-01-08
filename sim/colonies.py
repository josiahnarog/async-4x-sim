class Colony:
    def __init__(self, owner, level: int = 0, homeworld: bool = False):
        self.owner = owner
        self.level = level
        self.homeworld = homeworld

    def production(self) -> int:
        if self.homeworld:
            return 30
        return [0, 1, 3, 5][min(self.level, 3)]
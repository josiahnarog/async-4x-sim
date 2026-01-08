class Colony:
    def __init__(self, owner, level: int = 0, homeworld: bool = False):
        self.owner = owner
        self.level = int(level)
        self.homeworld = bool(homeworld)
        self.minerals_delivered = 0  # optional, if you implemented delivery earlier

    def production(self) -> int:
        if self.homeworld:
            return 30
        return [0, 1, 3, 5][min(self.level, 3)]

    def advance_econ(self) -> None:
        if self.homeworld:
            return
        self.level = min(self.level + 1, 3)

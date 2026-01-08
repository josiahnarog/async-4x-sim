from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Set

from sim.hexgrid import Hex
from sim.map_content import HexContent
from sim.colonies import Colony


@dataclass
class GameMap:
    q_min: int
    q_max: int
    r_min: int
    r_max: int

    blocked: Set[Hex] = field(default_factory=set)
    explored: Set[Hex] = field(default_factory=set)  # global explored tiles for now

    hex_contents: Dict[Hex, HexContent] = field(default_factory=dict)

    def in_bounds(self, h: Hex) -> bool:
        return self.q_min <= h.q <= self.q_max and self.r_min <= h.r <= self.r_max

    def is_blocked(self, h: Hex) -> bool:
        return h in self.blocked

    def is_passable(self, h: Hex) -> bool:
        return self.in_bounds(h) and not self.is_blocked(h)

    def block(self, h: Hex) -> None:
        if self.in_bounds(h):
            self.blocked.add(h)

    def unblock(self, h: Hex) -> None:
        self.blocked.discard(h)

    def is_explored(self, h: Hex) -> bool:
        return h in self.explored

    def set_explored(self, h: Hex) -> None:
        if self.in_bounds(h):
            self.explored.add(h)

    def neighbors_passable(self, h: Hex) -> Iterable[Hex]:
        for n in h.neighbors():
            if self.is_passable(n):
                yield n

    def set_hex_content(self, hex_: Hex, content: HexContent) -> None:
        self.hex_contents[hex_] = content

    def get_hex_content(self, hex_: Hex) -> HexContent:
        return self.hex_contents.get(hex_, HexContent.CLEAR)

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from sim.hexgrid import Hex


@dataclass(frozen=True)
class MoveOrder:
    group_id: str
    dest: Hex

    def __str__(self) -> str:
        return f"move {self.group_id} {self.dest.q} {self.dest.r}"


Order = Union[MoveOrder]
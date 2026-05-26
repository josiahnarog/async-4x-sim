"""Ship design — blueprint shared between ship designer, tactical encounters, and campaign."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ShipDesign:
    design_id:     str
    name:          str               # class name, e.g. "Broadside-class Destroyer"
    hull_type_id:  str               # key into tactical.hull_types.HULL_TYPES
    systems_str:   str               # compact system-track notation
    required_tech: frozenset[str] = field(default_factory=frozenset)

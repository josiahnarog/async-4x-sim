"""Global registry of ship designs.

Built-in designs are registered at module import time.  Campaign code and the
ship designer can call register() to add additional designs at runtime.
"""

from __future__ import annotations

from ships.design import ShipDesign

_registry: dict[str, ShipDesign] = {}


def register(design: ShipDesign) -> ShipDesign:
    _registry[design.design_id] = design
    return design


def get(design_id: str) -> ShipDesign:
    return _registry[design_id]


def all_designs() -> list[ShipDesign]:
    return list(_registry.values())


# ---------------------------------------------------------------------------
# Built-in starter designs
# ---------------------------------------------------------------------------

BROADSIDE_CLASS = register(ShipDesign(
    design_id="dd_broadside",
    name="Broadside-class Destroyer",
    hull_type_id="DD",
    systems_str="SSSSSAAAAA(I)FFRRQD(I)(I)(I)",
))

RAIDER_CLASS = register(ShipDesign(
    design_id="fg_raider",
    name="Raider-class Frigate",
    hull_type_id="FG",
    systems_str="SSSSSAAAAA(I)FFRRQD(I)(I)(I)",
))

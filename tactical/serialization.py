"""Pure encode/decode for all tactical game objects.

All public functions follow one of two signatures:
  encode_<type>(obj) -> JSON-serializable dict/list/scalar
  decode_<type>(d)   -> reconstructed object

No I/O is performed here; callers handle reading/writing JSON.
"""
from __future__ import annotations

import random
from typing import Any, Optional

from sim.hexgrid import Hex
from tactical.facing import Facing
from tactical.fighter_class import FIGHTER_CLASSES, FighterClass
from tactical.hull_types import HULL_TYPES, HullType
from tactical.initiative import Initiative
from tactical.ship_systems import System, ShipSystems, SystemStatus
from tactical.ship_state import ShipState
from tactical.squadron_state import FighterLoadout, SquadronState
from tactical.battle_state import BattleState
from tactical.weapons import WeaponType


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def encode_hex(h: Hex) -> dict:
    return {"q": h.q, "r": h.r}

def decode_hex(d: dict) -> Hex:
    return Hex(d["q"], d["r"])


def encode_facing(f: Facing) -> int:
    return int(f)

def decode_facing(v: int) -> Facing:
    return Facing(v)


def encode_hull_type(ht: HullType | None) -> str | None:
    if ht is None:
        return None
    return ht.designation

def decode_hull_type(s: str | None) -> HullType | None:
    if s is None:
        return None
    return HULL_TYPES[s]


# ---------------------------------------------------------------------------
# ShipSystems
# ---------------------------------------------------------------------------

def encode_system(s: System) -> dict:
    d: dict = {
        "base": s.base,
        "mods": s.mods,
        "status": s.status.value,
        "charges": s.charges,
    }
    if s.group is not None:
        d["group"] = s.group
    if s.occupant is not None:
        d["occupant"] = s.occupant
    return d

def decode_system(d: dict) -> System:
    return System(
        base=d["base"],
        mods=d.get("mods", ""),
        status=SystemStatus(d["status"]),
        group=d.get("group"),
        charges=d.get("charges", 0),
        occupant=d.get("occupant"),
    )


def encode_ship_systems(ss: ShipSystems | None) -> list | None:
    if ss is None:
        return None
    return [encode_system(s) for s in ss.systems]

def decode_ship_systems(d: list | None) -> ShipSystems | None:
    if d is None:
        return None
    return ShipSystems(tuple(decode_system(s) for s in d))


# ---------------------------------------------------------------------------
# ShipState
# ---------------------------------------------------------------------------

def encode_ship_state(ship: ShipState) -> dict:
    return {
        "ship_id": ship.ship_id,
        "owner_id": ship.owner_id,
        "pos": encode_hex(ship.pos),
        "facing": encode_facing(ship.facing),
        "mp": ship.mp,
        "turn_cost": ship.turn_cost,
        "turn_charge": ship.turn_charge,
        "systems": encode_ship_systems(ship.systems),
        "hull_type": encode_hull_type(ship.hull_type),
    }

def decode_ship_state(d: dict) -> ShipState:
    return ShipState(
        ship_id=d["ship_id"],
        owner_id=d["owner_id"],
        pos=decode_hex(d["pos"]),
        facing=decode_facing(d["facing"]),
        mp=d["mp"],
        turn_cost=d["turn_cost"],
        turn_charge=d.get("turn_charge", 0),
        systems=decode_ship_systems(d.get("systems")),
        hull_type=decode_hull_type(d.get("hull_type")),
    )


# ---------------------------------------------------------------------------
# FighterLoadout / SquadronState
# ---------------------------------------------------------------------------

def encode_fighter_class(fc: FighterClass) -> str:
    return fc.designation

def decode_fighter_class(s: str) -> FighterClass:
    return FIGHTER_CLASSES[s]


def encode_fighter_loadout(fl: FighterLoadout) -> dict:
    return {
        "fighter_class": encode_fighter_class(fl.fighter_class),
        "internal": [wt.value for wt in fl.internal],
        "external": [wt.value for wt in fl.external],
        "external_shots_remaining": fl.external_shots_remaining,
    }

def decode_fighter_loadout(d: dict) -> FighterLoadout:
    return FighterLoadout(
        fighter_class=decode_fighter_class(d["fighter_class"]),
        internal=tuple(WeaponType(w) for w in d.get("internal", [])),
        external=tuple(WeaponType(w) for w in d.get("external", [])),
        external_shots_remaining=d.get("external_shots_remaining", 0),
    )


def encode_squadron_state(sq: SquadronState) -> dict:
    return {
        "squadron_id": sq.squadron_id,
        "owner_id": sq.owner_id,
        "pos": encode_hex(sq.pos),
        "strength": sq.strength,
        "max_strength": sq.max_strength,
        "loadout": encode_fighter_loadout(sq.loadout),
        "endurance": sq.endurance,
        "max_endurance": sq.max_endurance,
        "docked_at": sq.docked_at,
    }

def decode_squadron_state(d: dict) -> SquadronState:
    return SquadronState(
        squadron_id=d["squadron_id"],
        owner_id=d["owner_id"],
        pos=decode_hex(d["pos"]),
        strength=d["strength"],
        max_strength=d["max_strength"],
        loadout=decode_fighter_loadout(d["loadout"]),
        endurance=d["endurance"],
        max_endurance=d["max_endurance"],
        docked_at=d.get("docked_at"),
    )


# ---------------------------------------------------------------------------
# BattleState
# ---------------------------------------------------------------------------

def encode_battle_state(b: BattleState) -> dict:
    return {
        "ships": {sid: encode_ship_state(s) for sid, s in b.ships.items()},
        "squadrons": {sqid: encode_squadron_state(sq) for sqid, sq in b.squadrons.items()},
    }

def decode_battle_state(d: dict) -> BattleState:
    return BattleState(
        ships={sid: decode_ship_state(s) for sid, s in d["ships"].items()},
        squadrons={sqid: decode_squadron_state(sq) for sqid, sq in d.get("squadrons", {}).items()},
    )


# ---------------------------------------------------------------------------
# Initiative
# ---------------------------------------------------------------------------

def encode_initiative(init: Initiative) -> dict:
    return {"rolls": dict(init.rolls)}

def decode_initiative(d: dict) -> Initiative:
    return Initiative(rolls=d["rolls"])


# ---------------------------------------------------------------------------
# Orders (tagged union)
# ---------------------------------------------------------------------------

def encode_ship_move_order(o) -> dict:
    return {
        "type": "ShipMoveOrder",
        "dest": encode_hex(o.dest),
        "dest_facing": encode_facing(o.dest_facing),
        "path": [encode_hex(h) for h in o.path],
        "total_mp_cost": o.total_mp_cost,
        "final_turn_charge": o.final_turn_charge,
    }

def decode_ship_move_order(d: dict):
    from tactical.turn_orders import ShipMoveOrder
    return ShipMoveOrder(
        dest=decode_hex(d["dest"]),
        dest_facing=decode_facing(d["dest_facing"]),
        path=tuple(decode_hex(h) for h in d.get("path", [])),
        total_mp_cost=d.get("total_mp_cost", 0),
        final_turn_charge=d.get("final_turn_charge", 0),
    )


def encode_ship_fire_order(o) -> dict | None:
    if o is None:
        return None
    return {"type": "ShipFireOrder", "target_id": o.target_id}

def decode_ship_fire_order(d: dict | None):
    if d is None:
        return None
    from tactical.turn_orders import ShipFireOrder
    return ShipFireOrder(target_id=d["target_id"])


def encode_squadron_order(o) -> dict:
    from tactical.turn_orders import (
        InterceptOrder, MoveOrder, StrikeOrder, BreakOffOrder, RecoverOrder,
    )
    if isinstance(o, InterceptOrder):
        d: dict = {
            "type": "InterceptOrder",
            "patrol_hex": encode_hex(o.patrol_hex),
        }
        if o.max_intercept_radius is not None:
            d["max_intercept_radius"] = o.max_intercept_radius
        return d
    if isinstance(o, MoveOrder):
        return {"type": "MoveOrder", "dest": encode_hex(o.dest)}
    if isinstance(o, StrikeOrder):
        return {"type": "StrikeOrder", "target_id": o.target_id}
    if isinstance(o, BreakOffOrder):
        return {"type": "BreakOffOrder", "dest": encode_hex(o.dest)}
    if isinstance(o, RecoverOrder):
        return {"type": "RecoverOrder", "carrier_id": o.carrier_id}
    raise ValueError(f"Unknown squadron order type: {type(o)}")

def decode_squadron_order(d: dict):
    from tactical.turn_orders import (
        InterceptOrder, MoveOrder, StrikeOrder, BreakOffOrder, RecoverOrder,
    )
    t = d["type"]
    if t == "InterceptOrder":
        return InterceptOrder(
            patrol_hex=decode_hex(d["patrol_hex"]),
            max_intercept_radius=d.get("max_intercept_radius"),
        )
    if t == "MoveOrder":
        return MoveOrder(dest=decode_hex(d["dest"]))
    if t == "StrikeOrder":
        return StrikeOrder(target_id=d["target_id"])
    if t == "BreakOffOrder":
        return BreakOffOrder(dest=decode_hex(d["dest"]))
    if t == "RecoverOrder":
        return RecoverOrder(carrier_id=d["carrier_id"])
    raise ValueError(f"Unknown squadron order type tag: {t!r}")


def encode_launch_order(o) -> dict:
    return {"type": "LaunchOrder", "squadron_id": o.squadron_id}

def decode_launch_order(d: dict):
    from tactical.turn_orders import LaunchOrder
    return LaunchOrder(squadron_id=d["squadron_id"])


# ---------------------------------------------------------------------------
# Encounter
# ---------------------------------------------------------------------------

def encode_encounter(enc) -> dict:
    from tactical.encounter import Phase
    return {
        "battle": encode_battle_state(enc.battle),
        "initiative": encode_initiative(enc.initiative),
        "phase": enc.phase.value,
        "move_orders": {
            sid: encode_ship_move_order(o)
            for sid, o in enc._move_orders.items()
        },
        "move_committed": list(enc._move_committed),
        "fire_orders": {
            sid: encode_ship_fire_order(o)
            for sid, o in enc._fire_orders.items()
        },
        "fire_committed": list(enc._fire_committed),
        "mp_capacity": dict(enc._mp_capacity),
        "squadron_orders": {
            sqid: encode_squadron_order(o)
            for sqid, o in enc._squadron_orders.items()
        },
        "squadron_committed": list(enc._squadron_committed),
        "launch_orders": {
            carrier_id: [encode_launch_order(lo) for lo in orders]
            for carrier_id, orders in enc._launch_orders.items()
        },
        "knowledge": {
            side: dict(unit_map)
            for side, unit_map in enc._knowledge.items()
        },
        "revealed_systems": {
            ship_id: list(indices)
            for ship_id, indices in enc._revealed_systems.items()
        },
    }

def decode_encounter(d: dict):
    from tactical.encounter import Encounter, Phase
    return Encounter(
        battle=decode_battle_state(d["battle"]),
        initiative=decode_initiative(d["initiative"]),
        phase=Phase(d["phase"]),
        _move_orders={
            sid: decode_ship_move_order(o)
            for sid, o in d.get("move_orders", {}).items()
        },
        _move_committed=frozenset(d.get("move_committed", [])),
        _fire_orders={
            sid: decode_ship_fire_order(o)
            for sid, o in d.get("fire_orders", {}).items()
        },
        _fire_committed=frozenset(d.get("fire_committed", [])),
        _mp_capacity=d.get("mp_capacity", {}),
        _squadron_orders={
            sqid: decode_squadron_order(o)
            for sqid, o in d.get("squadron_orders", {}).items()
        },
        _squadron_committed=frozenset(d.get("squadron_committed", [])),
        _launch_orders={
            carrier_id: [decode_launch_order(lo) for lo in orders]
            for carrier_id, orders in d.get("launch_orders", {}).items()
        },
        _knowledge={
            side: dict(unit_map)
            for side, unit_map in d.get("knowledge", {}).items()
        },
        _revealed_systems={
            ship_id: frozenset(indices)
            for ship_id, indices in d.get("revealed_systems", {}).items()
        },
    )


# ---------------------------------------------------------------------------
# RNG state
# ---------------------------------------------------------------------------

def encode_rng(rng: random.Random) -> list:
    """Encode RNG state as a JSON-serializable list.

    random.Random.getstate() returns (version, internalstate, gauss_next).
    internalstate is a tuple of 626 ints; gauss_next is float or None.
    We serialise as [version, [int, ...], gauss_next].
    """
    version, internalstate, gauss_next = rng.getstate()
    return [version, list(internalstate), gauss_next]

def decode_rng(data: list) -> random.Random:
    version, internalstate, gauss_next = data
    r = random.Random()
    r.setstate((version, tuple(internalstate), gauss_next))
    return r


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def encode_fire_event(ev) -> dict:
    d: dict = {
        "type": "FireEvent",
        "attacker_id": ev.attacker_id,
        "target_id": ev.target_id,
        "weapon": ev.weapon.value,
        "range": ev.range,
        "roll": ev.roll,
        "to_hit": ev.to_hit,
        "hit": ev.hit,
        "raw_damage": ev.raw_damage,
        "ammo_consumed": ev.ammo_consumed,
    }
    if ev.missile_hits is not None:
        d["missile_hits"] = ev.missile_hits
    if ev.pd_intercepted is not None:
        d["pd_intercepted"] = ev.pd_intercepted
    if ev.remaining_hits is not None:
        d["remaining_hits"] = ev.remaining_hits
    if ev.missile_rolls is not None:
        d["missile_rolls"] = list(ev.missile_rolls)
    if ev.pd_rolls is not None:
        d["pd_rolls"] = list(ev.pd_rolls)
    if ev.needle_penetration_roll is not None:
        d["needle_penetration_roll"] = ev.needle_penetration_roll
    if ev.needle_target_idx is not None:
        d["needle_target_idx"] = ev.needle_target_idx
    return d


def encode_fighter_shot_event(ev) -> dict:
    return {
        "type": "FighterShotEvent",
        "weapon": ev.weapon.value,
        "roll": ev.roll,
        "to_hit": ev.to_hit,
        "hit": ev.hit,
        "damage": ev.damage,
    }


def encode_dogfight_event(ev) -> dict:
    return {
        "type": "DogfightEvent",
        "attacker_id": ev.attacker_id,
        "target_id": ev.target_id,
        "mvr_delta": ev.mvr_delta,
        "shots": [encode_fighter_shot_event(s) for s in ev.shots],
        "total_casualties": ev.total_casualties,
    }


def encode_attack_run_event(ev) -> dict:
    return {
        "type": "AttackRunEvent",
        "attacker_id": ev.attacker_id,
        "target_id": ev.target_id,
        "pd_shots_fired": ev.pd_shots_fired,
        "pd_hits": ev.pd_hits,
        "pd_rolls": list(ev.pd_rolls),
        "fighters_killed_by_pd": ev.fighters_killed_by_pd,
        "surviving_strength": ev.surviving_strength,
        "weapon_shots": [encode_fighter_shot_event(s) for s in ev.weapon_shots],
        "total_ship_damage": ev.total_ship_damage,
    }


def encode_break_off_event(ev) -> dict:
    return {
        "type": "BreakOffEvent",
        "squadron_id": ev.squadron_id,
        "dest": encode_hex(ev.dest),
        "parting_shots": [encode_dogfight_event(s) for s in ev.parting_shots],
        "casualties_taken": ev.casualties_taken,
        "final_pos": encode_hex(ev.final_pos),
    }


def encode_unit_destroyed_event(ev) -> dict:
    return {
        "type": "UnitDestroyedEvent",
        "unit_id": ev.unit_id,
        "cause": ev.cause.value,
    }


def encode_fuel_warning_event(ev) -> dict:
    return {"type": "FuelWarningEvent", "squadron_id": ev.squadron_id}


def encode_launch_event(ev) -> dict:
    return {
        "type": "LaunchEvent",
        "carrier_id": ev.carrier_id,
        "squadron_id": ev.squadron_id,
        "pos": encode_hex(ev.pos),
    }


def encode_recovery_event(ev) -> dict:
    return {
        "type": "RecoveryEvent",
        "squadron_id": ev.squadron_id,
        "carrier_id": ev.carrier_id,
    }


def encode_battle_end_event(ev) -> dict:
    return {
        "type": "BattleEndEvent",
        "surviving_sides": list(ev.surviving_sides),
    }


def encode_event(ev) -> dict:
    """Dispatch encode for any tactical event type."""
    from tactical.combat import FireEvent
    from tactical.events import (
        UnitDestroyedEvent, FuelWarningEvent, LaunchEvent,
        RecoveryEvent, BattleEndEvent,
    )
    from tactical.fighter_events import (
        FighterShotEvent, DogfightEvent, AttackRunEvent, BreakOffEvent,
    )

    if isinstance(ev, FireEvent):
        return encode_fire_event(ev)
    if isinstance(ev, FighterShotEvent):
        return encode_fighter_shot_event(ev)
    if isinstance(ev, DogfightEvent):
        return encode_dogfight_event(ev)
    if isinstance(ev, AttackRunEvent):
        return encode_attack_run_event(ev)
    if isinstance(ev, BreakOffEvent):
        return encode_break_off_event(ev)
    if isinstance(ev, UnitDestroyedEvent):
        return encode_unit_destroyed_event(ev)
    if isinstance(ev, FuelWarningEvent):
        return encode_fuel_warning_event(ev)
    if isinstance(ev, LaunchEvent):
        return encode_launch_event(ev)
    if isinstance(ev, RecoveryEvent):
        return encode_recovery_event(ev)
    if isinstance(ev, BattleEndEvent):
        return encode_battle_end_event(ev)
    raise ValueError(f"Unknown event type: {type(ev)}")


def encode_events(events: list) -> list[dict]:
    return [encode_event(ev) for ev in events]

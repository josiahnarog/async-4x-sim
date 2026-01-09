# sim/persistence.py
from __future__ import annotations

import json
from typing import Any, Iterable

from sim.colonies import Colony
from sim.hexgrid import Hex
from sim.map import GameMap
from sim.map_content import HexContent
from sim.turn_engine import GameState
from sim.units import PlayerID, UnitGroup, UnitType

try:
    # Base ZIP guarantees MoveOrder; newer code may add more Order types.
    from sim.orders import MoveOrder  # type: ignore
except Exception:  # pragma: no cover
    MoveOrder = None  # type: ignore


SCHEMA_VERSION = 1


def _hex_key(h: Hex) -> str:
    return f"{h.q},{h.r}"


def _hex_from_key(s: str) -> Hex:
    q_s, r_s = s.split(",", 1)
    return Hex(int(q_s), int(r_s))


def _player_key(p: PlayerID) -> str:
    return p.name


def _players_from_names(names: Iterable[str]) -> dict[str, PlayerID]:
    return {n: PlayerID(n) for n in names}


def _unit_type_to_dict(ut: UnitType) -> dict[str, Any]:
    return {
        "name": ut.name,
        "max_groups": ut.max_groups,
        "movement": ut.movement,
        "is_combatant": ut.is_combatant,
        "initiative": ut.initiative,
        "attack": ut.attack,
        "defense": ut.defense,
        "hull": ut.hull,
        "builtin_cloak": getattr(ut, "builtin_cloak", 0),
        "builtin_sensors": getattr(ut, "builtin_sensors", 0),
        "can_colonize": getattr(ut, "can_colonize", False),
        "can_mine": getattr(ut, "can_mine", False),
        "upkeep_per_hull": getattr(
            ut,
            "upkeep_per_hull",
            1 if getattr(ut, "is_combatant", True) else 0,
        ),
    }


def _unit_type_from_dict(d: dict[str, Any]) -> UnitType:
    ut = UnitType(
        name=d["name"],
        max_groups=int(d.get("max_groups", 99)),
        movement=int(d.get("movement", 1)),
        is_combatant=bool(d.get("is_combatant", True)),
        initiative=d.get("initiative", "C"),
        attack=int(d.get("attack", 0)),
        defense=int(d.get("defense", 0)),
        hull=int(d.get("hull", 1)),
        builtin_cloak=int(d.get("builtin_cloak", 0)),
        builtin_sensors=int(d.get("builtin_sensors", 0)),
        can_colonize=bool(d.get("can_colonize", False)),
        can_mine=bool(d.get("can_mine", False)),
    )
    if "upkeep_per_hull" in d:
        ut.upkeep_per_hull = int(d["upkeep_per_hull"])
    return ut


def _group_to_dict(g: UnitGroup) -> dict[str, Any]:
    return {
        "group_id": g.group_id,
        "owner": _player_key(g.owner),
        "unit_type": _unit_type_to_dict(g.unit_type),
        "count": g.count,
        "location": _hex_key(g.location),
        "tactics": getattr(g, "tactics", 0),
        "cloak_bonus": getattr(g, "cloak_bonus", 0),
        "sensors_bonus": getattr(g, "sensors_bonus", 0),
        "attack_bonus": getattr(g, "attack_bonus", 0),
        "defense_bonus": getattr(g, "defense_bonus", 0),
        "damage": getattr(g, "damage", 0),
        # Cargo *should* be on UnitGroup; if older code stores it on UnitType, fall back.
        "cargo_minerals": getattr(g, "cargo_minerals", getattr(g.unit_type, "cargo_minerals", 0)),
    }


def _group_from_dict(d: dict[str, Any], players: dict[str, PlayerID]) -> UnitGroup:
    ut = _unit_type_from_dict(d["unit_type"])
    owner = players[d["owner"]]
    g = UnitGroup(
        group_id=d["group_id"],
        owner=owner,
        unit_type=ut,
        count=int(d.get("count", 1)),
        location=_hex_from_key(d["location"]),
        tactics=int(d.get("tactics", 0)),
        cloak_bonus=int(d.get("cloak_bonus", 0)),
        sensors_bonus=int(d.get("sensors_bonus", 0)),
        attack_bonus=int(d.get("attack_bonus", 0)),
        defense_bonus=int(d.get("defense_bonus", 0)),
    )
    g.damage = int(d.get("damage", 0))
    if hasattr(g, "cargo_minerals"):
        g.cargo_minerals = int(d.get("cargo_minerals", 0))
    return g


def _map_to_dict(m: GameMap) -> dict[str, Any]:
    return {
        "bounds": {"q_min": m.q_min, "q_max": m.q_max, "r_min": m.r_min, "r_max": m.r_max},
        "blocked": sorted((_hex_key(h) for h in m.blocked)),
        "explored": sorted((_hex_key(h) for h in m.explored)),
        "hex_contents": {_hex_key(h): c.name for h, c in m.hex_contents.items()},
    }


def _map_from_dict(d: dict[str, Any]) -> GameMap:
    b = d["bounds"]
    m = GameMap(
        q_min=int(b["q_min"]),
        q_max=int(b["q_max"]),
        r_min=int(b["r_min"]),
        r_max=int(b["r_max"]),
    )
    for s in d.get("blocked", []):
        m.blocked.add(_hex_from_key(s))
    for s in d.get("explored", []):
        m.explored.add(_hex_from_key(s))
    for k, v in d.get("hex_contents", {}).items():
        m.hex_contents[_hex_from_key(k)] = HexContent[v]
    return m


def _colony_to_dict(loc: Hex, c: Colony) -> dict[str, Any]:
    return {
        "location": _hex_key(loc),
        "owner": _player_key(c.owner),
        "level": int(getattr(c, "level", 0)),
        "homeworld": bool(getattr(c, "homeworld", False)),
        "minerals_delivered": int(getattr(c, "minerals_delivered", 0)),
    }


def _colony_from_dict(d: dict[str, Any], players: dict[str, PlayerID]) -> tuple[Hex, Colony]:
    loc = _hex_from_key(d["location"])
    owner = players[d["owner"]]
    c = Colony(owner=owner, level=int(d.get("level", 0)), homeworld=bool(d.get("homeworld", False)))
    if hasattr(c, "minerals_delivered") and "minerals_delivered" in d:
        c.minerals_delivered = int(d["minerals_delivered"])
    return loc, c


def _orders_to_list(orders: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for o in orders:
        # MoveOrder is the only guaranteed type in the base ZIP.
        if MoveOrder is not None and isinstance(o, MoveOrder):
            out.append({"type": "move", "group_id": o.group_id, "dest": _hex_key(o.dest)})
            continue

        # Best-effort for newer order types (ColonizeOrder/MineOrder/DeliverOrder/etc.)
        t = o.__class__.__name__.lower().replace("order", "")
        payload: dict[str, Any] = {"type": t}
        if hasattr(o, "group_id"):
            payload["group_id"] = getattr(o, "group_id")
        if hasattr(o, "dest") and isinstance(getattr(o, "dest"), Hex):
            payload["dest"] = _hex_key(getattr(o, "dest"))
        out.append(payload)
    return out


def _orders_from_list(items: list[dict[str, Any]]) -> list[Any]:
    # Import order classes lazily to support partial deployments.
    from sim.orders import MoveOrder  # guaranteed in this repo

    created: list[Any] = []
    for it in items:
        t = it.get("type")
        if t == "move":
            created.append(MoveOrder(it["group_id"], _hex_from_key(it["dest"])))
            continue

        # Optional newer types (safe to ignore if not present).
        if t in ("colonize", "mine", "deliver"):
            try:
                if t == "colonize":
                    from sim.orders import ColonizeOrder  # type: ignore
                    created.append(ColonizeOrder(it["group_id"]))
                elif t == "mine":
                    from sim.orders import MineOrder  # type: ignore
                    created.append(MineOrder(it["group_id"]))
                elif t == "deliver":
                    from sim.orders import DeliverOrder  # type: ignore
                    created.append(DeliverOrder(it["group_id"]))
            except Exception:
                # If the codebase doesn't define these yet, drop them.
                pass
    return created


def game_to_dict(game: GameState) -> dict[str, Any]:
    if game.active_player is None:
        raise ValueError("GameState.active_player must be set to serialize.")

    players = [_player_key(p) for p in game.players]
    active = _player_key(game.active_player)

    groups = [_group_to_dict(game.unit_groups[k]) for k in sorted(game.unit_groups.keys())]
    colonies = [
        _colony_to_dict(loc, c)
        for loc, c in sorted(game.colonies.items(), key=lambda kv: (kv[0].q, kv[0].r))
    ]

    revealed_to = {_player_key(viewer): sorted(list(gids)) for viewer, gids in game.revealed_to.items()}
    marker_for_viewer = {_player_key(viewer): dict(mapping) for viewer, mapping in game.marker_for_viewer.items()}
    group_for_viewer_marker = {
        _player_key(viewer): dict(mapping) for viewer, mapping in game.group_for_viewer_marker.items()
    }
    next_marker_index = {_player_key(viewer): int(n) for viewer, n in game.next_marker_index.items()}

    pending_orders: dict[str, Any] = {}
    for p, olist in game.pending_orders.items():
        pending_orders[_player_key(p)] = _orders_to_list(list(olist))

    credits: dict[str, int] = {_player_key(p): int(v) for p, v in game.credits.items()}

    return {
        "schema_version": SCHEMA_VERSION,
        "players": players,
        "active_player": active,
        "turn_number": int(getattr(game, "turn_number", 1)),
        "round_number": int(getattr(game, "round_number", 1)),
        "credits": credits,
        "map": _map_to_dict(game.game_map),
        "groups": groups,
        "colonies": colonies,
        "revealed_to": revealed_to,
        "marker_for_viewer": marker_for_viewer,
        "group_for_viewer_marker": group_for_viewer_marker,
        "next_marker_index": next_marker_index,
        "pending_orders": pending_orders,
        "log": list(game.log),
        "next_group_id": {_player_key(p): int(n) for p, n in getattr(game, "next_group_id", {}).items()},
        "next_unit_group_id": {_player_key(p): int(n) for p, n in getattr(game, "next_unit_group_id", {}).items()},
    }


def game_from_dict(data: dict[str, Any]) -> GameState:
    if int(data.get("schema_version", 0)) != SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema_version: {data.get('schema_version')}")

    names = list(data["players"])
    players = _players_from_names(names)

    game = GameState()
    game.players = [players[n] for n in names]
    game.active_player = players[data["active_player"]]

    game.turn_number = int(data.get("turn_number", 1))
    if hasattr(game, "round_number"):
        game.round_number = int(data.get("round_number", 1))

    game.game_map = _map_from_dict(data["map"])

    game.unit_groups = {}
    for g_d in data.get("groups", []):
        g = _group_from_dict(g_d, players)
        game.unit_groups[g.group_id] = g

    game.colonies = {}
    for c_d in data.get("colonies", []):
        loc, c = _colony_from_dict(c_d, players)
        game.colonies[loc] = c

    game.log = list(data.get("log", []))

    game.revealed_to = {}
    for viewer_name, gids in data.get("revealed_to", {}).items():
        game.revealed_to[players[viewer_name]] = set(gids)

    game.marker_for_viewer = {}
    for viewer_name, mapping in data.get("marker_for_viewer", {}).items():
        game.marker_for_viewer[players[viewer_name]] = dict(mapping)

    game.group_for_viewer_marker = {}
    for viewer_name, mapping in data.get("group_for_viewer_marker", {}).items():
        game.group_for_viewer_marker[players[viewer_name]] = dict(mapping)

    game.next_marker_index = {}
    for viewer_name, n in data.get("next_marker_index", {}).items():
        game.next_marker_index[players[viewer_name]] = int(n)

    game.pending_orders = {}
    for p_name, items in data.get("pending_orders", {}).items():
        game.pending_orders[players[p_name]] = _orders_from_list(list(items))

    game.credits = {players[p_name]: int(v) for p_name, v in data.get("credits", {}).items()}

    if hasattr(game, "next_group_id"):
        game.next_group_id = {players[p_name]: int(v) for p_name, v in data.get("next_group_id", {}).items()}
    if hasattr(game, "next_unit_group_id"):
        game.next_unit_group_id = {players[p_name]: int(v) for p_name, v in data.get("next_unit_group_id", {}).items()}

    return game


def game_to_json(game: GameState) -> str:
    return json.dumps(game_to_dict(game), sort_keys=True)


def game_from_json(s: str) -> GameState:
    return game_from_dict(json.loads(s))

from __future__ import annotations

import random

from sim.hexgrid import Hex
from tactical.battle_state import BattleState
from tactical.encounter import Encounter, Phase
from tactical.facing import Facing
from tactical.hull_types import FG
from tactical.render_ascii import render_tactical_grid_ascii
from tactical.ship_state import ShipState
from tactical.ship_systems import ShipSystems


def _fmt_ship(s: ShipState) -> str:
    return (
        f"{s.ship_id:>3} owner={s.owner_id} pos=({s.pos.q:+},{s.pos.r:+}) "
        f"face={int(s.facing)} mp={s.mp} "
        f"systems=[{s.systems.render_compact() if s.systems else '-'}]"
    )


def _format_fire_event(ev) -> str:
    if getattr(ev, "missile_rolls", None) is not None:
        to_hit = ev.to_hit
        roll_detail = ", ".join(
            f"{r}{'✓' if to_hit is not None and r <= to_hit else '✗'}"
            for r in ev.missile_rolls
        )
        pd_detail = ""
        if ev.pd_rolls:
            pd_to_hit = 3
            pd_roll_str = ", ".join(
                f"{r}{'✓' if r <= pd_to_hit else '✗'}"
                for r in ev.pd_rolls
            )
            pd_detail = f" pd_rolls=[{pd_roll_str}] pd_int={ev.pd_intercepted}"
        else:
            pd_detail = f" pd_int={ev.pd_intercepted}"
        return (
            f"{ev.attacker_id} -> {ev.target_id} w={ev.weapon.value} r={ev.range} "
            f"to_hit={ev.to_hit} rolls=[{roll_detail}] hits={ev.missile_hits}"
            f"{pd_detail} rem={ev.remaining_hits} dmg={ev.raw_damage}"
        )
    return (
        f"{ev.attacker_id} -> {ev.target_id} w={ev.weapon.value} r={ev.range} "
        f"roll={ev.roll} to_hit={ev.to_hit} hit={ev.hit} dmg={ev.raw_damage}"
    )


def _fmt_draft(d: dict) -> str:
    facing_names = ["N", "NE", "SE", "S", "SW", "NW"]
    hexes = " → ".join(f"({h.q},{h.r})" for h in d["path"])
    return (
        f"{hexes}  facing={facing_names[d['facing']]}"
        f"  mp_left={d['mp_remaining']}  charge={d['turn_charge']}/{d['turn_cost']}"
    )


def _print_state(enc: Encounter, drafts: dict | None = None) -> None:
    print()
    print(f"PHASE: {enc.phase.value}")
    print(f"  initiative: {enc.initiative.rolls}")

    if enc.phase == Phase.MOVE_SUBMISSION:
        committed = sorted(enc._move_committed)
        staged    = {sid: f"→({o.dest.q},{o.dest.r}) f={int(o.dest_facing)}"
                     for sid, o in enc._move_orders.items()}
        print(f"  committed: {committed}")
        print(f"  staged moves: {staged or 'none'}")
        if drafts:
            print("  DRAFT PATHS:")
            for sid, d in drafts.items():
                print(f"    {sid}: {_fmt_draft(d)}")
    elif enc.phase == Phase.COMBAT_SUBMISSION:
        committed = sorted(enc._fire_committed)
        staged    = {sid: (f"→{o.target_id}" if o else "PASS")
                     for sid, o in enc._fire_orders.items()}
        print(f"  committed: {committed}")
        print(f"  staged fire: {staged or 'none'}")

    print("SHIPS:")
    for sid in enc.battle.ship_ids_sorted():
        print(" ", _fmt_ship(enc.battle.ships[sid]))

    print()
    print("MAP:")
    print(render_tactical_grid_ascii(enc.battle, radius=6, empty=".."))


def _scenario_missiles_vs_pd() -> Encounter:
    """Close-range missile/PD scenario for testing."""
    a1 = ShipState(
        ship_id="A1",
        owner_id="A",
        pos=Hex(0, 0),
        facing=Facing.N,
        mp=0,
        turn_cost=3,
        turn_charge=0,
        systems=ShipSystems.parse("RRRR"),
    )
    b1 = ShipState(
        ship_id="B1",
        owner_id="B",
        pos=Hex(0, 1),
        facing=Facing.S,
        mp=0,
        turn_cost=3,
        turn_charge=0,
        systems=ShipSystems.parse("SSAHDD"),
    )
    battle = BattleState(ships={"A1": a1, "B1": b1})
    return Encounter.start(battle)


def _help() -> None:
    print("Commands:")
    print("  show                       print current state")
    print("  map                        print hex map only")
    print("  scenario missiles          load missiles-vs-PD scenario")
    print()
    print("  --- MOVE_SUBMISSION phase ---")
    print("  move <ship_id> <steps>             build draft: N hexes forward in current facing")
    print("  tl/tr <ship_id>                    turn left/right in draft (requires full charge)")
    print("  spend <ship_id> <n>                spend N MP to charge turning")
    print("  move <ship_id> <q> <r> [facing]   stage move directly to hex (no draft)")
    print("  commit move <side_id>              commit moves for a side")
    print("  commit move                        commit moves for ALL sides")
    print()
    print("  --- COMBAT_SUBMISSION phase ---")
    print("  fireall <ship_id> <target_id>      stage: fire all weapons at target")
    print("  pass <ship_id>                     stage: explicit pass (no fire)")
    print("  commit fire <side_id>              commit fire orders for a side")
    print("  commit fire                        commit fire orders for ALL sides")
    print()
    print("  --- Debug (bypasses submission system) ---")
    print("  quickfire <attacker_id> <target_id>   immediate fire-all")
    print("  shoot <attacker_id> <target_id> <w>   immediate single-weapon fire")
    print()
    print("  quit")


def main() -> None:
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    rng = random.Random(1)

    _fg_systems = "SSSSSAAAAA(I)FFRRD(I)(I)(I)"
    a = ShipState(
        ship_id="A1",
        owner_id="A",
        pos=Hex(0, 0),
        facing=Facing.NE,
        mp=5,
        turn_cost=2,
        turn_charge=0,
        systems=ShipSystems.parse(_fg_systems),
        hull_type=FG,
    )
    b = ShipState(
        ship_id="B1",
        owner_id="B",
        pos=Hex(6, 0),
        facing=Facing.S,
        mp=5,
        turn_cost=2,
        turn_charge=0,
        systems=ShipSystems.parse(_fg_systems),
        hull_type=FG,
    )

    battle = BattleState(ships={"A1": a, "B1": b})
    enc = Encounter.start(battle, rng=rng)

    # Per-ship draft paths for movement construction
    # ship_id -> {"pos", "facing", "mp_remaining", "turn_charge", "turn_cost", "path", "mp_used"}
    drafts: dict = {}

    def get_or_create_draft(ship_id: str) -> dict:
        if ship_id not in drafts:
            ship = enc.battle.ships[ship_id]
            cap  = enc._mp_capacity.get(ship_id, ship.mp)
            drafts[ship_id] = {
                "pos":          ship.pos,
                "facing":       int(ship.facing),
                "mp_remaining": cap,
                "turn_charge":  ship.turn_charge,
                "turn_cost":    ship.turn_cost,
                "path":         [ship.pos],
                "mp_used":      0,
            }
        return drafts[ship_id]

    print("Tactical REPL")
    _help()
    _print_state(enc, drafts)

    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()

        try:
            if cmd in ("q", "quit", "exit"):
                break

            elif cmd == "help":
                _help()

            elif cmd == "map":
                print(render_tactical_grid_ascii(enc.battle, radius=6))

            elif cmd == "show":
                _print_state(enc, drafts)

            elif cmd == "scenario":
                if len(parts) != 2:
                    print("usage: scenario <name>  (available: missiles)")
                    continue
                name = parts[1].lower()
                if name == "missiles":
                    enc = _scenario_missiles_vs_pd()
                    drafts.clear()
                    _print_state(enc, drafts)
                else:
                    print(f"unknown scenario: {name!r}. available: missiles")

            elif cmd == "move":
                # move <ship_id> <steps>            — build draft forward N hexes
                # move <ship_id> <q> <r> [facing]  — stage directly to hex (no draft)
                if len(parts) < 3:
                    print("usage: move <ship_id> <steps>  OR  move <ship_id> <q> <r> [facing]")
                    continue
                ship_id = parts[1]
                if ship_id not in enc.battle.ships:
                    print(f"unknown ship: {ship_id!r}")
                    continue
                if enc.phase != Phase.MOVE_SUBMISSION:
                    print(f"Cannot move: phase is {enc.phase.value!r}")
                    continue

                if len(parts) == 3:
                    # Draft path: forward N steps
                    from tactical.facing import FACING_OFFSETS
                    steps = int(parts[2])
                    d = get_or_create_draft(ship_id)
                    if steps <= 0:
                        print("steps must be > 0")
                        continue
                    if steps > d["mp_remaining"]:
                        print(f"Only {d['mp_remaining']} MP remaining in draft")
                        continue
                    dq, dr = FACING_OFFSETS[d["facing"]]
                    pos = d["pos"]
                    for _ in range(steps):
                        pos = Hex(pos.q + dq, pos.r + dr)
                        d["path"].append(pos)
                    d["pos"]           = pos
                    d["mp_remaining"] -= steps
                    d["mp_used"]      += steps
                    d["turn_charge"]   = min(d["turn_charge"] + steps, d["turn_cost"])
                    facing_names = ["N", "NE", "SE", "S", "SW", "NW"]
                    print(f"Draft {ship_id}: +{steps} → ({pos.q},{pos.r})"
                          f"  mp_left={d['mp_remaining']}"
                          f"  charge={d['turn_charge']}/{d['turn_cost']}")
                else:
                    # Direct hex: stage immediately, no draft
                    ship = enc.battle.ships[ship_id]
                    dest = Hex(int(parts[2]), int(parts[3]))
                    dest_facing = Facing.from_int(int(parts[4])) if len(parts) >= 5 else ship.facing
                    enc = enc.stage_move(ship.owner_id, ship_id, dest, dest_facing)
                    print(f"Staged: {ship_id} → ({dest.q},{dest.r}) facing={int(dest_facing)}")
                _print_state(enc, drafts)

            elif cmd in ("tl", "tr"):
                if len(parts) != 2:
                    print(f"usage: {cmd} <ship_id>")
                    continue
                ship_id = parts[1]
                if ship_id not in enc.battle.ships:
                    print(f"unknown ship: {ship_id!r}")
                    continue
                if enc.phase != Phase.MOVE_SUBMISSION:
                    print(f"Cannot turn: phase is {enc.phase.value!r}")
                    continue
                d = get_or_create_draft(ship_id)
                if d["turn_charge"] < d["turn_cost"]:
                    print(f"Cannot turn: charge={d['turn_charge']}/{d['turn_cost']}"
                          f"  (use 'spend {ship_id} <n>' to charge)")
                    continue
                direction = +1 if cmd == "tr" else -1
                d["facing"]      = (d["facing"] + direction) % 6
                d["turn_charge"] = 0
                facing_names = ["N", "NE", "SE", "S", "SW", "NW"]
                print(f"Draft {ship_id}: turned → facing {facing_names[d['facing']]}")
                _print_state(enc, drafts)

            elif cmd == "spend":
                if len(parts) != 3:
                    print("usage: spend <ship_id> <amount>")
                    continue
                ship_id = parts[1]
                if ship_id not in enc.battle.ships:
                    print(f"unknown ship: {ship_id!r}")
                    continue
                if enc.phase != Phase.MOVE_SUBMISSION:
                    print(f"Cannot spend: phase is {enc.phase.value!r}")
                    continue
                amount = int(parts[2])
                d = get_or_create_draft(ship_id)
                if amount > d["mp_remaining"]:
                    print(f"Only {d['mp_remaining']} MP remaining in draft")
                    continue
                d["mp_remaining"] -= amount
                d["mp_used"]      += amount
                d["turn_charge"]   = min(d["turn_charge"] + amount, d["turn_cost"])
                print(f"Draft {ship_id}: spent {amount} MP"
                      f"  charge={d['turn_charge']}/{d['turn_cost']}"
                      f"  mp_left={d['mp_remaining']}")
                _print_state(enc, drafts)

            elif cmd == "commit":
                if len(parts) < 2:
                    print("usage: commit move [side_id]  |  commit fire [side_id]")
                    continue
                sub = parts[1].lower()
                if sub == "move":
                    if enc.phase != Phase.MOVE_SUBMISSION:
                        print(f"Not in MOVE_SUBMISSION phase (current: {enc.phase.value})")
                        continue
                    # Stage orders from all pending drafts
                    for ship_id, d in list(drafts.items()):
                        if ship_id not in enc.battle.ships:
                            continue
                        ship = enc.battle.ships[ship_id]
                        try:
                            enc = enc.stage_move(
                                ship.owner_id, ship_id,
                                d["pos"], Facing.from_int(d["facing"]),
                                path_cost=d["mp_used"],
                            )
                            print(f"Staged from draft: {ship_id} → ({d['pos'].q},{d['pos'].r})"
                                  f" facing={d['facing']} cost={d['mp_used']}")
                        except Exception as e:
                            print(f"Draft {ship_id} invalid: {e}")
                    drafts.clear()
                    sides_to_commit = (
                        [parts[2]] if len(parts) >= 3 else sorted(enc.sides() - enc._move_committed)
                    )
                    for s in sides_to_commit:
                        enc = enc.commit_movement(s)
                        print(f"Side {s!r} committed movement.")
                        if enc.phase == Phase.COMBAT_SUBMISSION:
                            print("→ Movement resolved. Entering COMBAT_SUBMISSION.")
                            break
                    _print_state(enc, drafts)
                elif sub == "fire":
                    if enc.phase != Phase.COMBAT_SUBMISSION:
                        print(f"Not in COMBAT_SUBMISSION phase (current: {enc.phase.value})")
                        continue
                    sides_to_commit = (
                        [parts[2]] if len(parts) >= 3 else sorted(enc.sides() - enc._fire_committed)
                    )
                    all_events: list = []
                    for s in sides_to_commit:
                        enc, events = enc.commit_fire(s, rng)
                        all_events.extend(events)
                        print(f"Side {s!r} committed fire orders.")
                        if enc.phase == Phase.COMBAT_SMALL:
                            print("→ Fire resolved. Entering COMBAT_SMALL.")
                            break
                    for ev in all_events:
                        print(_format_fire_event(ev))
                    _print_state(enc, drafts)
                else:
                    print("usage: commit move [side_id]  |  commit fire [side_id]")

            elif cmd == "fireall":
                if len(parts) != 3:
                    print("usage: fireall <ship_id> <target_id>")
                    continue
                ship_id, target_id = parts[1], parts[2]
                if ship_id not in enc.battle.ships:
                    print(f"unknown ship: {ship_id!r}")
                    continue
                side = enc.battle.ships[ship_id].owner_id
                enc = enc.stage_fire(side, ship_id, target_id)
                print(f"Staged: {ship_id} fires all weapons at {target_id}")
                _print_state(enc, drafts)

            elif cmd == "pass":
                if len(parts) != 2:
                    print("usage: pass <ship_id>")
                    continue
                ship_id = parts[1]
                if ship_id not in enc.battle.ships:
                    print(f"unknown ship: {ship_id!r}")
                    continue
                side = enc.battle.ships[ship_id].owner_id
                enc = enc.pass_fire(side, ship_id)
                print(f"Staged: {ship_id} passes fire")
                _print_state(enc, drafts)

            elif cmd == "shoot":
                if len(parts) != 4:
                    print("usage: shoot <attacker_id> <target_id> <weapon_code>")
                    print("examples: shoot A1 B1 R   |   shoot B1 A1 L")
                    continue
                attacker_id, target_id, wcode = parts[1], parts[2], parts[3].upper()
                from tactical.combat import resolve_large_fire
                from tactical.weapons import WeaponType
                try:
                    weapon = WeaponType(wcode)
                except Exception:
                    print(f"unknown weapon_code: {wcode!r}")
                    continue
                import dataclasses
                battle2, ev = resolve_large_fire(
                    enc.battle, attacker_id=attacker_id, target_id=target_id,
                    weapon=weapon, rng=rng,
                )
                enc = dataclasses.replace(enc, battle=battle2)
                print(_format_fire_event(ev))
                _print_state(enc, drafts)

            elif cmd == "quickfire":
                if len(parts) != 3:
                    print("usage: quickfire <attacker_id> <target_id>")
                    continue
                attacker_id, target_id = parts[1], parts[2]
                if attacker_id not in enc.battle.ships:
                    print(f"unknown ship: {attacker_id!r}")
                    continue
                import dataclasses
                from tactical.combat import resolve_fire_all
                enc_battle, events = resolve_fire_all(
                    enc.battle, attacker_id=attacker_id, target_id=target_id, rng=rng,
                )
                enc = dataclasses.replace(enc, battle=enc_battle)
                if not events:
                    print(f"{attacker_id} has no active weapons.")
                for ev in events:
                    print(_format_fire_event(ev))
                _print_state(enc, drafts)

            else:
                print(f"unknown command: {cmd!r}. type 'help' for list.")

        except Exception as e:
            print(f"ERROR: {e}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import random

from sim.hexgrid import Hex
from tactical.battle_state import BattleState
from tactical.encounter import Encounter, Phase
from tactical.facing import Facing
from tactical.render_ascii import render_tactical_grid_ascii
from tactical.ship_state import ShipState
from tactical.ship_systems import ShipSystems


def _fmt_ship(s: ShipState) -> str:
    return (
        f"{s.ship_id:>3} owner={s.owner_id} pos=({s.pos.q:+},{s.pos.r:+}) "
        f"face={int(s.facing)} mp={s.mp} tc={s.turn_cost} ch={s.turn_charge} "
        f"systems=[{s.systems.render_compact() if s.systems else '-'}]"
    )


def format_fire_event(ev) -> str:
    parts = [
        f"{ev.attacker_id} -> {ev.target_id}",
        f"w={ev.weapon.value}",
        f"r={ev.range}",
        f"to_hit={ev.to_hit}",
        f"roll={ev.roll}",
        f"hit={ev.hit}",
        f"dmg={ev.raw_damage}",
    ]
    if ev.missile_hits is not None:
        parts.append(f"missile_hits={ev.missile_hits}")
        parts.append(f"pd_int={ev.pd_intercepted}")
        parts.append(f"rem={ev.remaining_hits}")
    return " | ".join(parts)


def _print_state(enc: Encounter) -> None:
    print()
    print(f"PHASE: {enc.phase.value}")
    if enc.phase == Phase.MOVEMENT:
        print(f"  movement subphase: {enc.movement_subphase_index + 1}/{enc.movement_subphases}")
        print(f"  active side (low->high): {enc.active_side()}  rolls={enc.initiative.rolls}")
    elif enc.phase == Phase.COMBAT_LARGE:
        print(f"  active side (high->low): {enc.active_large_combat_side()}  rolls={enc.initiative.rolls}")
        print(f"  spent_to_fire: {sorted(enc.spent_to_fire)}")
    else:
        print(f"  rolls={enc.initiative.rolls}")

    print("SHIPS:")
    for sid in enc.battle.ship_ids_sorted():
        print(" ", _fmt_ship(enc.battle.ships[sid]))

    print()
    print("MAP:")
    print(render_tactical_grid_ascii(enc.battle, radius=6, empty=".."))


def _scenario_missiles_vs_pd() -> "Encounter":
    """
    Creates a close-range scenario designed to exercise:
      - missile volley size (multiple R launchers)
      - point defense interception
      - damage application to ShipSystems

    A1 at (0,0) facing N, systems=RRRR
    B1 at (0,1) facing S, systems=SSAHDD
    """
    from sim.hexgrid import Hex
    from tactical.facing import Facing
    from tactical.ship_state import ShipState
    from tactical.ship_systems import ShipSystems
    from tactical.battle_state import BattleState
    from tactical.encounter import Encounter

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
    # Encounter constructor signature may differ; adjust if needed.
    return Encounter(battle=battle)

def _format_fire_event(ev) -> str:
    # keep it simple and readable in REPL
    s = f"{ev.attacker_id} -> {ev.target_id} w={ev.weapon.value} r={ev.range} roll={ev.roll} to_hit={ev.to_hit} hit={ev.hit} dmg={ev.raw_damage}"
    if getattr(ev, "missile_hits", None) is not None:
        s += f" | missile_hits={ev.missile_hits} pd_int={ev.pd_intercepted} rem={ev.remaining_hits}"
    return s


def main() -> None:
    rng = random.Random(1)

    # Tiny starter scenario: 2 sides, 1 ship each.
    a = ShipState(
        ship_id="A1",
        owner_id="A",
        pos=Hex(0, 0),
        facing=Facing.N,
        mp=6,
        turn_cost=3,
        turn_charge=0,
        systems=ShipSystems.parse("IIII"),  # capacity=4 per subphase refresh
    )
    b = ShipState(
        ship_id="B1",
        owner_id="B",
        pos=Hex(6, 0),
        facing=Facing.S,
        mp=6,
        turn_cost=3,
        turn_charge=0,
        systems=ShipSystems.parse("III"),  # capacity=3 per subphase refresh
    )

    battle = BattleState(ships={"A1": a, "B1": b})
    enc = Encounter.start(battle, rng=rng, movement_subphases=3)

    print("Tactical REPL")
    print("Commands:")
    print("  map")
    print("  show")
    print("  move <ship_id> <steps>")
    print("  tl <ship_id> [steps]  (turn left; free but requires full charge)")
    print("  tr <ship_id> [steps]  (turn right; free but requires full charge)")
    print("  spend <ship_id> <mp>")
    print("  end                 (end active side movement; enforces required spend)")
    print("  fire <ship_id>      (COMBAT_LARGE only; marks ship spent)")
    print("  pass <ship_id>      (COMBAT_LARGE only; marks ship spent)")
    print("  next                (COMBAT_LARGE only; advance to next combat side / cycle)")
    print("  quit")
    _print_state(enc)

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

            if cmd == "map":
                print(render_tactical_grid_ascii(enc.battle, radius=6))
                continue

            if cmd == "shoot":
                if len(parts) != 4:
                    print("usage: shoot <attacker_id> <target_id> <weapon_code>")
                    print("examples: shoot A1 B1 R   |   shoot B1 A1 L")
                    continue
                attacker_id = parts[1]
                target_id = parts[2]
                wcode = parts[3].upper()

                from tactical.combat import resolve_large_fire
                from tactical.weapons import WeaponType

                try:
                    weapon = WeaponType(wcode)
                except Exception:
                    print(f"unknown weapon_code: {wcode!r}")
                    continue

                # Use encounter's rng if you have one; otherwise a deterministic default.
                # If Encounter already stores rng, swap this line accordingly.
                import random
                rng = random.Random(0)

                battle2, ev = resolve_large_fire(
                    enc.battle,
                    attacker_id=attacker_id,
                    target_id=target_id,
                    weapon=weapon,
                    rng=rng,
                )
                enc = type(enc)(**{**enc.__dict__, "battle": battle2})  # functional update

                print(_format_fire_event(ev))
                _print_state(enc)
                continue


            if cmd == "scenario":
                if len(parts) != 2:
                    print("usage: scenario <name>")
                    print("available: missiles")
                    continue
                name = parts[1].lower()
                if name == "missiles":
                    enc = _scenario_missiles_vs_pd()
                    _print_state(enc)
                    continue
                print(f"unknown scenario: {name!r}. available: missiles")
                continue

            if cmd == "show":
                _print_state(enc)
                continue

            if cmd == "move":
                if len(parts) != 3:
                    print("usage: move <ship_id> <steps>")
                    continue
                ship_id = parts[1]
                steps = int(parts[2])
                side = enc.active_side()
                enc = enc.move_ship_forward(side, ship_id, steps=steps)
                _print_state(enc)
                continue

            if cmd == "tl":
                if len(parts) != 2:
                    print("usage: tl <ship_id>")
                    continue
                ship_id = parts[1]
                side = enc.active_side()
                enc = enc.turn_ship_left(side, ship_id, auto_spend=False)
                _print_state(enc)
                continue

            if cmd == "tr":
                if len(parts) != 2:
                    print("usage: tr <ship_id>")
                    continue
                ship_id = parts[1]
                side = enc.active_side()
                enc = enc.turn_ship_right(side, ship_id, auto_spend=False)
                _print_state(enc)
                continue

            if cmd == "tla":
                if len(parts) != 2:
                    print("usage: tla <ship_id>")
                    continue
                ship_id = parts[1]
                side = enc.active_side()
                enc = enc.turn_ship_left(side, ship_id, auto_spend=True)
                _print_state(enc)
                continue

            if cmd == "tra":
                if len(parts) != 2:
                    print("usage: tra <ship_id>")
                    continue
                ship_id = parts[1]
                side = enc.active_side()
                enc = enc.turn_ship_right(side, ship_id, auto_spend=True)
                _print_state(enc)
                continue

            if cmd == "spend":
                if len(parts) != 3:
                    print("usage: spend <ship_id> <mp>")
                    continue
                ship_id = parts[1]
                amount = int(parts[2])
                side = enc.active_side()
                enc = enc.spend_mp(side, ship_id, amount)
                _print_state(enc)
                continue

            if cmd == "end":
                side = enc.active_side()
                enc = enc.end_side_movement(side)
                _print_state(enc)
                continue

            if cmd == "fire":
                if len(parts) != 2:
                    print("usage: fire <ship_id>")
                    continue
                ship_id = parts[1]
                side = enc.active_large_combat_side()
                enc = enc.choose_unit_to_fire(side, ship_id)
                _print_state(enc)
                continue

            if cmd == "pass":
                if len(parts) != 2:
                    print("usage: pass <ship_id>")
                    continue
                ship_id = parts[1]
                side = enc.active_large_combat_side()
                enc = enc.pass_fire(side, ship_id)
                _print_state(enc)
                continue

            if cmd == "next":
                enc = enc.advance_combat_turn()
                _print_state(enc)
                continue

            print(f"unknown command: {cmd!r}. try: show/move/spend/end/fire/pass/next/quit")

        except Exception as e:
            print(f"ERROR: {e}")


if __name__ == "__main__":
    main()

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

from sim.render_ascii import render_map_ascii, RenderBounds
from sim.hexgrid import Hex
from sim.movement import move_group


def run_repl(game):
    print("Async 4X Simulator")
    print("Type 'help' for commands.\n")

    while True:
        prompt = f"[Turn {game.turn_number} | Player {game.active_player}]> "
        cmd = input(prompt).strip().lower()

        if cmd in ("quit", "exit"):
            break

        elif cmd == "help":
            print("Commands:")
            print("  map                 - show visible map")
            print("  mygroups            - list your groups")
            print("  move G1 q r         - move group to axial hex (q,r)")
            print("  log                 - show recent game log")
            print("  end                 - end your turn")

        elif cmd == "map":
            render_map_ascii(game)

        elif cmd == "mygroups":
            show_mygroups(game)

        elif cmd == "end":
            game.end_turn()

        elif cmd.startswith("inspect"):
            parts = cmd.split()
            if len(parts) != 2:
                print("Usage: inspect <group_id>")
            else:
                inspect_group(game, parts[1].upper())

        elif cmd.startswith("move "):
            handle_move(game, cmd)

        elif cmd == "log":
            # show last ~20 messages
            for line in game.log[-20:]:
                print(" ", line)

        else:
            print("Unknown command")


def show_map(game):
    bounds = RenderBounds(-3, 3, -3, 3)
    print(render_map_ascii(game, bounds=bounds))


def show_mygroups(game):
    for g in game.unit_groups.values():
        if g.owner == game.active_player:
            print(f"  {g.group_id} ({g.unit_type.name}, {g.count}) at {g.location}")


def inspect_group(game, group_id):
    group = game.unit_groups.get(group_id)

    if not group:
        print("No such group.")
        return

    # Fog-of-war rule:
    # You may inspect if you own it
    if group.owner == game.active_player:
        print(f"Group {group.group_id}")
        print(f"  Owner: {group.owner}")
        print(f"  Type: {group.unit_type.name}")
        print(f"  Count: {group.count}")
        print(f"  Tech level: {group.tech_level}")
        print(f"  Location: {group.location}")
    else:
        print(f"Group {group.group_id}")
        print(f"  Owner: {group.owner}")
        print("  Details unknown (fog of war)")


def handle_move(game, cmd: str) -> None:
    # Usage: move G1 1 0
    parts = cmd.split()
    if len(parts) != 4:
        print("Usage: move <GROUP_ID> <q> <r>")
        return

    _, group_id, q_str, r_str = parts
    group_id = group_id.upper()  # normalize so "g1" works too

    try:
        q = int(q_str)
        r = int(r_str)
    except ValueError:
        print("q and r must be integers. Example: move G1 1 0")
        return

    from sim.hexgrid import Hex
    ok, msg = game.move_group(group_id, Hex(q, r))
    print(msg)

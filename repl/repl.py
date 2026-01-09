from sim.render_ascii import render_map_ascii
from sim.hexgrid import Hex


def run_repl(game):
    print("Async 4X Simulator")
    print("Type 'help' for commands. Type 'exit' to quit.\n")

    while True:
        prompt = f"[Turn {game.turn_number} | Player {game.active_player}]> "
        raw = input(prompt).strip()
        cmd = raw.lower()

        if cmd in ("quit", "exit"):
            break

        elif cmd == "help":
            print("Commands:")
            print("  map                         - show ascii map (fog-aware)")
            print("  mygroups                     - list your groups (full info)")
            print("  inspect <group_id>           - inspect a group you own (full) or enemy marker (limited)")
            print("  stack <q> <r>                - list groups at a hex (fog-aware)")
            print("  move <group_id> <q> <r>      - move one group (range + interception)")
            print("  movefleet <q> <r> <q2> <r2>  - move all your groups from one hex (range + interception)")
            print("  log                          - show recent game log")
            print("  end                          - end your turn")
            print("  orders                       - display current order queue")
            print("  undo                         - remove most recent order from queue")
            print("  submit                       - submit all orders and end turn")
            print("  move!                        - immediately execute move as server command")
            print("  explored                     - print explored hexes")
            print("  colonize <group_id>           - queue colonize action (resolves on submit)")
            print("  mine <group_id>               - queue mine action (resolves on submit)")
            print("  colonize! <group_id>          - execute colonize immediately (debug/manual)")
            print("  mine! <group_id>              - execute mine immediately (debug/manual)")

        elif cmd == "map":
            print(render_map_ascii(game, game.active_player))

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

        elif cmd.startswith("stack "):
            handle_stack(game, cmd)

        elif cmd.startswith("movefleet "):
            handle_movefleet(game, cmd)

        elif cmd.startswith("move! "):
            handle_move(game, cmd.replace("move!", "move", 1).strip(), execute_immediately=True)

        elif cmd.startswith("move "):
            handle_move(game, cmd, execute_immediately=False)

        elif cmd == "log":
            if not game.log:
                print("(no events)")
            else:
                for line in game.log[-20:]:
                    print(" ", line)

        elif cmd == "orders":
            orders = game.list_orders()
            if not orders:
                print("(no pending orders)")
            else:
                for i, o in enumerate(orders, start=1):
                    print(f"  {i}. {o}")

        elif cmd == "undo":
            ok, msg = game.undo_last_order()
            print(msg)

        elif cmd == "clearorders":
            ok, msg = game.clear_orders()
            print(msg)

        elif cmd == "submit":
            events = game.submit_orders()
            for e in events:
                print(e)

        elif cmd.startswith("block "):
            parts = raw.split()
            if len(parts) != 3:
                print("Usage: block <q> <r>")
            else:
                q, r = int(parts[1]), int(parts[2])
                from sim.hexgrid import Hex
                h = Hex(q, r)
                game.game_map.block(h)
                print(f"Blocked {h}")

        elif cmd.startswith("unblock "):
            parts = raw.split()
            if len(parts) != 3:
                print("Usage: unblock <q> <r>")
            else:
                q, r = int(parts[1]), int(parts[2])
                from sim.hexgrid import Hex
                h = Hex(q, r)
                game.game_map.unblock(h)
                print(f"Unblocked {h}")

        elif cmd.startswith("path "):
            parts = raw.split()
            if len(parts) != 4:
                print("Usage: path <GROUP_ID> <q> <r>")
            else:
                gid = parts[1].upper()
                q, r = int(parts[2]), int(parts[3])
                from sim.hexgrid import Hex
                from sim.pathfinding import bfs_path

                g = game.get_group(gid)
                if not g:
                    print("No such group.")
                else:
                    dest = Hex(q, r)
                    path = bfs_path(game.game_map, g.location, dest)
                    if path is None:
                        print("No path.")
                    else:
                        print("Path:", " -> ".join(str(h) for h in path))
                        print(f"Steps: {len(path)}  Movement: {g.movement}")

        elif cmd == "explored":
            if hasattr(game, "game_map") and game.game_map is not None and hasattr(game.game_map, "explored"):
                xs = sorted(game.game_map.explored, key=lambda h: (h.q, h.r))
                print(f"Explored tiles: {len(xs)}")
                for h in xs[:30]:
                    print(" ", h)
                if len(xs) > 30:
                    print("  ...")
            else:
                print("No exploration state on map.")

        elif cmd.startswith("colonize! "):
            handle_colonize_now(game, raw)

        elif cmd.startswith("mine! "):
            handle_mine_now(game, raw)

        elif cmd.startswith("colonize "):
            handle_colonize(game, raw)

        elif cmd.startswith("mine "):
            handle_mine(game, raw)

        elif cmd == "reveal":
            handle_reveal(game, cmd)

        elif cmd == "revealall":
            handle_revealall(game, cmd)


        else:
            print("Unknown command")


def show_mygroups(game):
    found = False
    for g in game.unit_groups.values():
        if g.owner == game.active_player:
            found = True
            print(f"  {g.group_id} ({g.unit_type.name}, {g.count}) at {g.location}")
    if not found:
        print("  (none)")


def inspect_group(game, token: str):
    gid = game.resolve_group_id_from_token(game.active_player, token)
    if not gid:
        print("No such group (or unknown marker).")
        return

    g = game.unit_groups.get(gid)
    if not g:
        print("That group no longer exists.")
        return

    if g.owner == game.active_player:
        print(f"{g.group_id} (OWNER VIEW)")
        print(f"  Type: {g.unit_type.name}")
        print(f"  Count: {g.count}")
        print(f"  Location: {g.location}")
        return

    # Enemy group:
    if game.is_revealed(game.active_player, g.group_id):
        print(f"{g.group_id} (REVEALED ENEMY)")
        print(f"  Owner: {g.owner}")
        print(f"  Type: {g.unit_type.name}")
        print(f"  Count: {g.count}")
        print(f"  Location: {g.location}")
    else:
        mid = game.get_marker_id(game.active_player, g.group_id)
        print(f"{mid} (ENEMY MARKER)")
        print(f"  Location: {g.location}")
        print("  Details hidden until revealed")


def handle_move(game, cmd: str, execute_immediately: bool = False) -> None:
    parts = cmd.split()
    if len(parts) != 4:
        print("Usage: move <GROUP_ID> <q> <r>")
        return

    _, group_id, q_str, r_str = parts
    group_id = group_id.strip().upper()
    try:
        q = int(q_str);
        r = int(r_str)
    except ValueError:
        print("q and r must be integers.")
        return

    dest = Hex(q, r)

    if execute_immediately:
        ok, msg = game.move_group(group_id, dest)
        print(msg)
        return

    ok, msg = game.queue_move(group_id, dest)
    print(msg)


def handle_movefleet(game, cmd: str) -> None:
    parts = cmd.split()
    if len(parts) != 5:
        print("Usage: movefleet <q> <r> <q2> <r2>")
        return

    _, q1s, r1s, q2s, r2s = parts
    try:
        q1, r1, q2, r2 = int(q1s), int(r1s), int(q2s), int(r2s)
    except ValueError:
        print("All coordinates must be integers. Example: movefleet 0 0 2 0")
        return

    msgs = game.move_fleet(Hex(q1, r1), Hex(q2, r2))
    for m in msgs:
        print(m)


def handle_stack(game, cmd: str) -> None:
    parts = cmd.split()
    if len(parts) != 3:
        print("Usage: stack <q> <r>")
        return

    _, qs, rs = parts
    try:
        q, r = int(qs), int(rs)
    except ValueError:
        print("q and r must be integers. Example: stack 0 0")
        return

    hx = Hex(q, r)
    groups = game.groups_at(hx)
    if not groups:
        print(f"(no groups at {hx})")
        return

    print(f"Groups at {hx}:")
    for g in groups:
        if g.owner == game.active_player:
            print(f"  {g.group_id} ({g.unit_type.name}, {g.count}, tech {g.tech_level}) owner {g.owner}")
        else:
            print(f"  ?? (enemy marker) owner {g.owner}")


def handle_colonize(game, cmd: str) -> None:
    parts = cmd.split()
    if len(parts) != 2:
        print("Usage: colonize <group_id>")
        return
    gid = parts[1]
    ok, msg = game.queue_colonize(gid)
    print(msg)
    if not ok:
        return


def handle_colonize_now(game, cmd: str) -> None:
    parts = cmd.split()
    if len(parts) != 2:
        print("Usage: colonize! <group_id>")
        return
    gid = parts[1]
    for e in game.manual_colonize(gid):
        print(e)


def handle_mine(game, cmd: str) -> None:
    parts = cmd.split()
    if len(parts) != 2:
        print("Usage: mine <group_id>")
        return
    gid = parts[1]
    ok, msg = game.queue_mine(gid)
    print(msg)
    if not ok:
        return




def handle_reveal(game, cmd: str) -> None:
    parts = cmd.split()
    if len(parts) != 3:
        print("Usage: reveal <q> <r>")
        return
    try:
        q = int(parts[1])
        r = int(parts[2])
    except ValueError:
        print("q and r must be integers.")
        return

    for e in game.debug_reveal_hex(Hex(q, r)):
        print(e)


def handle_revealall(game, cmd: str) -> None:
    parts = cmd.split()
    if len(parts) != 1:
        print("Usage: revealall")
        return
    for e in game.debug_reveal_all_hexes():
        print(e)


def show_stack(game, q: int, r: int):
    from sim.hexgrid import Hex
    h = Hex(q, r)
    occ = game.groups_at(h)
    if not occ:
        print("(empty)")
        return

    print(f"Stack at {h}:")
    for g in occ:
        if g.owner == game.active_player:
            print(f"  {g.group_id}: {g.unit_type.name} x{g.count} (t{g.tech_level})")
        else:
            if game.is_revealed(game.active_player, g.group_id):
                print(f"  {g.group_id} (revealed): {g.unit_type.name} x{g.count} (t{g.tech_level}) owner={g.owner}")
            else:
                mid = game.get_marker_id(game.active_player, g.group_id)
                print(f"  {mid}: enemy group (hidden)")

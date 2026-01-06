from sim.turn_engine import GameState
from sim.hexgrid import Hex
from sim.units import PlayerID, UnitType, UnitGroup


def build_game():
    game = GameState()

    A = PlayerID("A")
    B = PlayerID("B")

    game.players = [A, B]
    game.active_player = A

    battleship = UnitType("Battleship", max_groups=5, movement=3)
    decoy = UnitType("Decoy", max_groups=10, movement=3)

    g1 = UnitGroup("G1", A, battleship, count=3, tech_level=1, location=Hex(0, 0))
    g2 = UnitGroup("G2", B, decoy, count=1, tech_level=0, location=Hex(2, 0))

    game.add_group(g1)
    game.add_group(g2)

    return game


def test_queue_move_does_not_change_location():
    game = build_game()

    start = game.get_group("G1").location
    ok, _ = game.queue_move("G1", Hex(1, 0))
    assert ok

    # Still at start until submit
    assert game.get_group("G1").location == start


def test_submit_applies_move():
    game = build_game()

    game.queue_move("G1", Hex(1, 0))
    events = game.submit_orders()

    assert game.get_group("G1").location == Hex(1, 0)
    assert any("SUBMIT" in e for e in events)


def test_undo_removes_last_order():
    game = build_game()

    game.queue_move("G1", Hex(1, 0))
    game.queue_move("G1", Hex(2, 0))
    assert len(game.list_orders()) == 2

    ok, _ = game.undo_last_order()
    assert ok
    assert len(game.list_orders()) == 1
    assert "2 0" not in str(game.list_orders()[0])  # last order removed


def test_submit_ends_turn():
    game = build_game()
    A = game.active_player
    B = game.players[1]

    game.queue_move("G1", Hex(1, 0))
    game.submit_orders()

    assert game.active_player == B


def test_interception_removes_defender_on_submit():
    game = build_game()

    # Move G1 onto G2's hex; should trigger combat and remove G2
    game.queue_move("G1", Hex(2, 0))
    game.submit_orders()

    assert game.get_group("G2") is None


def test_submit_move_fails_if_no_path():
    game = build_game()
    # Block a ring or specifically block the goal:
    game.game_map.block(Hex(1, 0))
    game.game_map.block(Hex(1, -1))
    game.game_map.block(Hex(0, -1))
    # try to reach (1,0) which is blocked
    ok, _ = game.queue_move("G1", Hex(1, 0))
    assert ok
    events = game.submit_orders()
    # G1 should still be at (0,0)
    assert game.get_group("G1").location == Hex(0, 0)
    assert any("No path" in e or "blocked" in e for e in events)

from sim.turn_engine import GameState
from sim.hexgrid import Hex
from sim.units import PlayerID, UnitType, UnitGroup


def test_queue_move_does_not_change_location(game):
    start = game.get_group("G1").location
    ok, _ = game.queue_move("G1", Hex(1, 0))
    assert ok

    # Still at start until submit
    assert game.get_group("G1").location == start


def test_submit_applies_move(game):
    game.queue_move("G1", Hex(1, 0))
    events = game.submit_orders()

    assert game.get_group("G1").location == Hex(1, 0)
    assert any("SUBMIT" in e for e in events)


def test_undo_removes_last_order(game):

    game.queue_move("G1", Hex(1, 0))
    game.queue_move("G1", Hex(2, 0))
    assert len(game.list_orders()) == 2

    ok, _ = game.undo_last_order()
    assert ok
    assert len(game.list_orders()) == 1
    assert "2 0" not in str(game.list_orders()[0])  # last order removed


def test_submit_ends_turn(game):
    A = game.active_player
    B = game.players[1]

    game.queue_move("G1", Hex(1, 0))
    game.submit_orders()

    assert game.active_player == B


def test_interception_removes_defender_on_submit(game):

    # Move G1 onto G2's hex; should trigger combat and remove G2
    game.queue_move("G1", Hex(2, 0))
    game.submit_orders()

    assert game.get_group("G2") is None


def test_submit_move_fails_if_no_path(game):
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


def test_exploration_only_on_ended_hexes(game):
    # Assume start hex (0,0) is unexplored at game start
    start = Hex(0,0)
    if hasattr(game, "game_map"):
        assert not game.game_map.is_explored(start)

    # Submit with NO move orders
    events = game.submit_orders()
    # Should not explore anything just because a ship exists somewhere
    if hasattr(game, "game_map"):
        assert not game.game_map.is_explored(start)


def test_exploration_after_successful_move(game):
    dest = Hex(1,0)
    if hasattr(game, "game_map"):
        assert not game.game_map.is_explored(dest)

    game.queue_move("G1", dest)
    game.submit_orders()

    if hasattr(game, "game_map"):
        assert game.game_map.is_explored(dest)
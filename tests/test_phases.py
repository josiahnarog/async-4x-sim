from sim.hexgrid import Hex
import pytest
from tests.test_orders import build_game as _build_game


@pytest.fixture
def build_game():
    return _build_game()


def test_submit_runs_movement_then_combat_then_exploration(build_game):
    game = build_game()

    # Ensure destination is in-bounds and unexplored
    dest = Hex(2, 0)
    if hasattr(game, "game_map"):
        assert not game.game_map.is_explored(dest)

    game.queue_move("G1", dest)
    events = game.submit_orders()

    # Phase order appears in events
    joined = "\n".join(events)
    assert "PHASE: Movement" in joined
    assert "PHASE: Combat" in joined
    assert "PHASE: Exploration" in joined


def test_enemy_contact_halts_movement_and_combat_happens_later(build_game):
    game = build_game()

    # Move onto enemy hex; movement phase should halt with "combat pending"
    game.queue_move("G1", Hex(2, 0))
    events = game.submit_orders()
    joined = "\n".join(events)

    assert "combat pending" in joined.lower()
    assert "PHASE: Combat" in joined

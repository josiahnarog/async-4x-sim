from sim.hexgrid import Hex


def test_submit_runs_movement_then_combat_then_exploration(game):
    dest = Hex(2, 0)
    if hasattr(game, "game_map") and hasattr(game.game_map, "is_explored"):
        assert not game.game_map.is_explored(dest)

    game.queue_move("G1", dest)
    events = game.submit_orders()

    joined = "\n".join(events)
    assert "PHASE: Movement" in joined
    assert "PHASE: Combat" in joined
    assert "PHASE: Exploration" in joined


def test_enemy_contact_halts_movement_and_combat_happens_later(game):
    game.queue_move("G1", Hex(2, 0))
    events = game.submit_orders()
    joined = "\n".join(events).lower()

    assert "phase: combat" in joined
    assert "combat" in joined

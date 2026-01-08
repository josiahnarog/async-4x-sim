from sim.units import UnitType, UnitGroup, PlayerID
from sim.hexgrid import Hex
from sim.turn_engine import GameState
from sim.map import GameMap
from tests.conftest import dump_log


def test_submit_with_no_orders_passes_turn(game):

    start_player = game.active_player
    events = game.submit_orders()

    joined = "\n".join(events)
    assert "SUBMIT:" in joined
    assert "(0 order(s))" in joined
    assert "PHASE: Movement" in joined
    assert "PHASE: Combat" in joined
    assert "PHASE: Exploration" in joined
    assert game.active_player != start_player  # turn advanced


def test_economic_phase_triggers_every_three_rounds_when_passing(game):
    for p in game.players:
        game.credits.setdefault(p, 0)

    saw_econ = False

    # loop until we pass Round 3; should always happen well before this cap
    for _ in range(len(game.players) * 10):
        events = game.submit_orders()
        if any("PHASE: Economic" in e for e in events):
            saw_econ = True
            break
        if game.turn_number >= 3 and game.active_player == game.players[0]:
            # we should have just wrapped into round 3 at some point
            pass

    assert saw_econ, f"Expected economic phase to trigger; turn_number={game.turn_number}"




def test_noncombatants_default_upkeep_is_zero():
    ut = UnitType(name="Miner", max_groups=99, movement=1, is_combatant=False)
    assert getattr(ut, "upkeep_per_hull", 0) == 0


def test_upkeep_is_count_times_hull_times_per_hull():
    game = GameState()
    game.game_map = GameMap(q_min=-1, q_max=1, r_min=-1, r_max=1)

    p = PlayerID("A")
    game.players = [p]
    game.active_player = p
    game.credits[p] = 0

    ut = UnitType(name="Fighter", max_groups=99, movement=1, is_combatant=True, hull=2, attack=1, defense=0,
                  initiative="C")
    # upkeep_per_hull defaults to 1 for combatants
    g = UnitGroup("A1", p, ut, count=3, location=Hex(0, 0))
    game.add_group(g)

    assert game._econ_upkeep_for_player(p) == 3 * 2 * 1


def test_pass_advances_turn_and_includes_now_active(game):
    start = game.active_player
    events = game.submit_orders()
    assert game.active_player != start
    assert any(e.startswith("Now active:") for e in events)

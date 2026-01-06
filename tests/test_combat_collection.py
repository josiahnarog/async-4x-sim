from sim.hexgrid import Hex
from sim.combat import collect_battles


def test_collect_battles_finds_contested_hex(game):

    # In your default scenario, enemy at (2,0), friendly at (0,0)
    # Move into enemy to create a combat site on submit
    game.queue_move("G1", Hex(2, 0))
    game.submit_orders()

    # After submit, combat likely resolved and defender removed (placeholder)
    # So instead, directly construct a contested situation for test:
    # Put both owners in same hex.
    g1 = game.get_group("G1")
    g1.location = Hex(1, 0)

    # Create a new enemy group at same hex if G2 might have been destroyed
    if game.get_group("G2") is None:
        from sim.units import UnitType, UnitGroup, PlayerID
        B = game.players[1]
        decoy = UnitType("Decoy", max_groups=10, movement=3)
        g2 = UnitGroup("G2", B, decoy, count=1, tech_level=0, location=Hex(1, 0))
        game.add_group(g2)
    else:
        game.get_group("G2").location = Hex(1, 0)

    combat_sites = {Hex(1, 0)}
    battles = collect_battles(game, combat_sites)

    assert len(battles) == 1
    assert battles[0].location == Hex(1, 0)
    assert len(battles[0].owners) == 2

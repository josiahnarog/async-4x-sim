from sim.hexgrid import Hex


def test_pass_through_destroys_noncombat_and_continues(game):
    """
    Moving combat unit passes through non-combat enemy units,
    destroying them and continuing movement.
    """
    g1 = game.get_group("G1")  # battleship
    g2 = game.get_group("G2")  # decoy (non-combat)

    assert not g2.unit_type.is_combatant

    # Move through G2's hex and beyond
    dest = Hex(3, 0)
    game.queue_move("G1", dest)
    events = game.submit_orders()

    # Non-combatant destroyed
    assert game.get_group("G2") is None

    # Mover continued to destination
    assert game.get_group("G1").location == dest

    joined = "\n".join(events).lower()
    assert "destroyed during interception" in joined
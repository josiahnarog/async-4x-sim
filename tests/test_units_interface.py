def test_unitgroup_has_movement_property(game):
    g = game.get_group("G1")
    assert isinstance(g.movement, int)
    assert g.movement == g.unit_type.movement


def test_unitgroup_properties_exist(game):
    g = game.get_group("G1")
    _ = g.movement
    _ = g.initiative
    _ = g.attack
    _ = g.defense
    _ = g.hull
    _ = g.cloak_level
    _ = g.sensor_level
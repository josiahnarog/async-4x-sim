import pytest

from tactical.system_track import ShipSystems


def test_parse_and_render_roundtrip_preserves_groups():
    t = ShipSystems.parse("SSSAAALL(III)(III)")
    assert len(t.boxes) == 14
    assert t.render_compact() == "SSSAAALL(III)(III)"


def test_parse_supports_camel_case_tokens():
    t = ShipSystems.parse("XcXc(III)")
    assert len(t.boxes) == 5
    assert t.render_compact() == "XcXc(III)"


def test_apply_damage_left_to_right_and_marks_destroyed():
    t0 = ShipSystems.parse("SA(II)L")
    t1 = t0.apply_damage(2)
    assert t1.render_compact() == "!S!A(II)L"

    t2 = t1.apply_damage(1)
    assert t2.render_compact() == "!S!A(!II)L"
    assert t2.movement_points() == 1


def test_serialization_roundtrip_is_lossless():
    t0 = ShipSystems.parse("S(II)A")
    t1 = t0.apply_damage(1)

    data = t1.to_dict()
    t2 = ShipSystems.from_dict(data)

    assert t2 == t1
    assert t2.render_compact() == t1.render_compact()


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "(",
        "(SS",
        "SS)",
        "S1A",
        "S()",
        "sc",
        "(xC)",
    ],
)
def test_parse_rejects_invalid_compact_strings(bad: str):
    with pytest.raises(ValueError):
        ShipSystems.parse(bad)

"""Shock-shape generators (pure functions, no API)."""
import pytest

from oegem import profiles


def test_step_and_ramp():
    assert profiles.step(-0.5, 3) == [-0.5, -0.5, -0.5]
    assert profiles.ramp(1.0, 4) == [0.25, 0.5, 0.75, 1.0]


def test_linear_fade_matches_the_documented_example_and_ends_at_zero():
    assert profiles.linear_fade(20, hold=4, fade=4) == [20, 20, 20, 20, 15, 10, 5, 0]
    assert profiles.linear_fade(3, hold=0, fade=3) == [2.0, 1.0, 0.0]
    assert profiles.linear_fade(7, hold=2, fade=0) == [7, 7]


def test_decay_and_hump():
    assert profiles.decay(1.0, 0.5, 4) == [1.0, 0.5, 0.25, 0.125]
    assert profiles.hump(10, up=2, hold=1, fade=2) == [5, 10, 10, 5, 0]
    assert profiles.hump(4, up=0, hold=0, fade=2) == [2.0, 0.0]


def test_from_spec_kinds_and_aliases():
    assert profiles.from_spec({"kind": "linear_fade", "value": 20, "hold": 4, "fade": 4})[-1] == 0
    assert profiles.from_spec({"type": "step", "value": 2, "n": 2}) == [2, 2]
    assert profiles.from_spec({"kind": "hump", "value": 10, "up": 2, "hold": 1, "fade": 2}) == [5, 10, 10, 5, 0]
    assert profiles.from_spec({"kind": "decay", "value": 1, "rho": 0.5, "n": 2}) == [1, 0.5]
    assert profiles.from_spec({"kind": "ramp", "value": 2, "n": 2.0}) == [1, 2]


@pytest.mark.parametrize("spec, fragment", [
    ({"kind": "wiggle", "value": 1}, "Unknown profile kind"),
    ({"kind": "step", "value": 1}, "missing n"),
    ({"kind": "step", "value": 1, "n": 2, "hold": 3}, "unexpected hold"),
    ({"kind": "step", "value": 1, "n": 1.5}, "whole number"),
    ({"kind": "decay", "value": 1, "rho": 1.5, "n": 3}, "between 0 and 1"),
    ({"kind": "linear_fade", "value": "x", "hold": 1, "fade": 1}, "must be a number"),
    ("linear_fade", "must be a mapping"),
])
def test_from_spec_errors_say_how_to_fix(spec, fragment):
    with pytest.raises(ValueError, match=fragment):
        profiles.from_spec(spec)


def test_zero_length_profiles_are_rejected():
    with pytest.raises(ValueError):
        profiles.step(1, 0)
    with pytest.raises(ValueError):
        profiles.linear_fade(1, 0, 0)

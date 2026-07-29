"""Tests for the resolved per-room settings the rules read."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from custom_components.room_advisor.settings import (
    Direction,
    RoomSettings,
    Threshold,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

_BUILDERS: list[Callable[..., Threshold]] = [Threshold.rising, Threshold.falling]


def test_a_rising_band_sits_below_the_threshold() -> None:
    """Advice starts at the threshold and stops a whole band below it."""
    threshold = Threshold.rising(76.0, 1.0)
    assert threshold.activate_at == 76.0
    assert threshold.deactivate_at == 75.0
    assert threshold.direction is Direction.RISING


def test_a_falling_band_sits_above_the_threshold() -> None:
    """Advice starts at the threshold and stops a whole band above it."""
    threshold = Threshold.falling(63.0, 1.0)
    assert threshold.activate_at == 63.0
    assert threshold.deactivate_at == 64.0
    assert threshold.direction is Direction.FALLING


@pytest.mark.parametrize("build", _BUILDERS)
def test_a_threshold_without_a_band_has_one_boundary(
    build: Callable[..., Threshold],
) -> None:
    """An unconfigured band leaves a plain crossing point."""
    threshold = build(70.0)
    assert threshold.activate_at == threshold.deactivate_at == 70.0
    assert threshold.band == 0.0


@pytest.mark.parametrize("build", _BUILDERS)
def test_a_negative_band_is_rejected(build: Callable[..., Threshold]) -> None:
    """A band is a width, so it cannot be given as a negative number."""
    with pytest.raises(ValueError, match="cannot be negative"):
        build(70.0, -1.0)


def test_the_band_is_reported_as_a_width() -> None:
    """The band reads back the same either side of the threshold."""
    assert Threshold.rising(76.0, 1.5).band == 1.5
    assert Threshold.falling(63.0, 1.5).band == 1.5


@pytest.mark.parametrize(
    ("activate_at", "deactivate_at", "direction"),
    [
        (76.0, 77.0, Direction.RISING),
        (63.0, 62.0, Direction.FALLING),
    ],
)
def test_boundaries_on_the_wrong_side_are_rejected(
    activate_at: float,
    deactivate_at: float,
    direction: Direction,
) -> None:
    """A band on the activation side would leave advice unable to stop."""
    with pytest.raises(ValueError, match="deactivation side"):
        Threshold(activate_at, deactivate_at, direction)


@pytest.mark.parametrize(
    ("value", "active", "expected"),
    [
        (75.5, False, False),
        (76.0, False, True),
        (75.5, True, True),
        (74.9, True, False),
    ],
)
def test_a_rising_threshold_is_met_by_rising(
    value: float,
    active: bool,
    expected: bool,
) -> None:
    """Rising to the threshold meets it; falling past the band stops it."""
    assert Threshold.rising(76.0, 1.0).is_met(value, active=active) is expected


@pytest.mark.parametrize(
    ("value", "active", "expected"),
    [
        (63.5, False, False),
        (63.0, False, True),
        (63.5, True, True),
        (64.1, True, False),
    ],
)
def test_a_falling_threshold_is_met_by_falling(
    value: float,
    active: bool,
    expected: bool,
) -> None:
    """Falling to the threshold meets it; rising past the band stops it."""
    assert Threshold.falling(63.0, 1.0).is_met(value, active=active) is expected


def test_the_two_directions_are_not_interchangeable() -> None:
    """The same numbers read opposite ways round, which is why direction is kept."""
    value = 70.0
    assert Threshold.rising(65.0).is_met(value, active=False) is True
    assert Threshold.falling(65.0).is_met(value, active=False) is False


def _settings(
    *,
    thresholds: Mapping[str, Threshold] | None = None,
    durations: Mapping[str, timedelta] | None = None,
    activation_delays: Mapping[str, timedelta] | None = None,
) -> RoomSettings:
    """Build room settings, defaulting everything not under test."""
    return RoomSettings(
        thresholds=(
            {"indoor_hot": Threshold.rising(76.0, 1.0)}
            if thresholds is None
            else thresholds
        ),
        durations=(
            {"vacancy": timedelta(minutes=10)} if durations is None else durations
        ),
        activation_delays={} if activation_delays is None else activation_delays,
    )


def test_a_resolved_threshold_is_returned_by_name() -> None:
    """Rules reach a crossing point by name, not by rebuilding it."""
    assert _settings().threshold("indoor_hot").activate_at == 76.0


def test_a_resolved_duration_is_returned_by_name() -> None:
    """Durations resolve the same way thresholds do."""
    assert _settings().duration("vacancy") == timedelta(minutes=10)


@pytest.mark.parametrize("lookup", ["threshold", "duration"])
def test_an_unconfigured_setting_is_a_programming_error(lookup: str) -> None:
    """A missing setting is a mistake, not a room that opted out."""
    with pytest.raises(KeyError):
        getattr(_settings(), lookup)("nothing_of_the_sort")


def test_a_rule_keeps_its_own_delay_when_the_room_says_nothing() -> None:
    """A room overrides only the delays it cares about."""
    delay = _settings().activation_delay("window.rain_incoming", timedelta(minutes=2))
    assert delay == timedelta(minutes=2)


def test_a_room_can_override_a_rule_delay() -> None:
    """Delays are per rule and configurable per room."""
    settings = _settings(
        activation_delays={"window.rain_incoming": timedelta(seconds=30)}
    )
    delay = settings.activation_delay("window.rain_incoming", timedelta(minutes=2))
    assert delay == timedelta(seconds=30)


def test_settings_do_not_share_the_caller_s_mappings() -> None:
    """Settings are immutable for the life of the entry, including their contents."""
    durations = {"vacancy": timedelta(minutes=10)}
    settings = _settings(durations=durations)
    durations["vacancy"] = timedelta(minutes=1)
    assert settings.duration("vacancy") == timedelta(minutes=10)


def test_a_duration_cannot_run_backwards() -> None:
    """A room empty for minus ten minutes cannot mean anything."""
    with pytest.raises(ValueError, match="duration cannot be negative"):
        _settings(durations={"vacancy": timedelta(minutes=-10)})


def test_an_overridden_delay_cannot_run_backwards() -> None:
    """A room's override reaches the stabiliser, so it is checked like a rule's own."""
    with pytest.raises(ValueError, match="delay cannot be negative"):
        _settings(activation_delays={"window.rain_incoming": timedelta(seconds=-1)})

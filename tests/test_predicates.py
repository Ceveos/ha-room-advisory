"""Tests for the comparison helpers shared by the rules."""

from __future__ import annotations

import math

import pytest

from custom_components.room_advisor.models import GuardState
from custom_components.room_advisor.predicates import (
    above_with_hysteresis,
    below_with_hysteresis,
    guards_permit_opening,
)


def test_no_guards_permit_opening() -> None:
    """A rule that declares no guards is not blocked by them."""
    assert guards_permit_opening() is True


@pytest.mark.parametrize(
    ("state", "permits"),
    [
        (GuardState.NOT_CONFIGURED, True),
        (GuardState.SATISFIED, True),
        (GuardState.BLOCKING, False),
        (GuardState.UNUSABLE, False),
    ],
)
def test_each_guard_state(state: GuardState, permits: bool) -> None:
    """Only an unconfigured or satisfied guard permits opening."""
    assert guards_permit_opening(state) is permits


def test_an_unusable_guard_blocks_as_firmly_as_a_blocking_one() -> None:
    """A guard that cannot be read withholds the advice it protects."""
    assert (
        guards_permit_opening(
            GuardState.SATISFIED,
            GuardState.NOT_CONFIGURED,
            GuardState.UNUSABLE,
        )
        is False
    )


def test_one_blocking_guard_overrides_any_number_of_permitting_ones() -> None:
    """Guards are a conjunction, so permission is unanimous or absent."""
    assert (
        guards_permit_opening(
            GuardState.SATISFIED,
            GuardState.SATISFIED,
            GuardState.BLOCKING,
            GuardState.NOT_CONFIGURED,
        )
        is False
    )


def test_every_guard_state_is_covered_by_the_helper() -> None:
    """A new guard state cannot be silently treated as permitting."""
    permitting = {state for state in GuardState if guards_permit_opening(state)}
    assert permitting == {GuardState.NOT_CONFIGURED, GuardState.SATISFIED}


@pytest.mark.parametrize(
    ("value", "active", "expected"),
    [
        (76.0, False, False),
        (77.9, False, False),
        (78.0, False, True),
        (79.0, False, True),
        (79.0, True, True),
        (78.0, True, True),
        (77.5, True, True),
        (77.0, True, True),
        (76.9, True, False),
        (76.0, True, False),
    ],
)
def test_above_with_hysteresis(value: float, active: bool, expected: bool) -> None:
    """Rising to the threshold activates; falling below the band deactivates."""
    assert above_with_hysteresis(value, 78.0, 77.0, active=active) is expected


@pytest.mark.parametrize(
    ("value", "active", "expected"),
    [
        (66.0, False, False),
        (64.1, False, False),
        (64.0, False, True),
        (63.0, False, True),
        (63.0, True, True),
        (64.0, True, True),
        (64.5, True, True),
        (65.0, True, True),
        (65.1, True, False),
        (66.0, True, False),
    ],
)
def test_below_with_hysteresis(value: float, active: bool, expected: bool) -> None:
    """Falling to the threshold activates; rising above the band deactivates."""
    assert below_with_hysteresis(value, 64.0, 65.0, active=active) is expected


@pytest.mark.parametrize(
    ("value", "expected_when_inactive"),
    [(77.0, False), (77.4, False), (78.0, True)],
)
def test_inside_the_band_above_the_state_is_held(
    value: float,
    expected_when_inactive: bool,
) -> None:
    """Between the two boundaries the helper reports whatever it reported before."""
    assert above_with_hysteresis(value, 78.0, 77.0, active=True) is True
    assert (
        above_with_hysteresis(value, 78.0, 77.0, active=False) is expected_when_inactive
    )


@pytest.mark.parametrize(
    ("value", "expected_when_inactive"),
    [(65.0, False), (64.6, False), (64.0, True)],
)
def test_inside_the_band_below_the_state_is_held(
    value: float,
    expected_when_inactive: bool,
) -> None:
    """Between the two boundaries the helper reports whatever it reported before."""
    assert below_with_hysteresis(value, 64.0, 65.0, active=True) is True
    assert (
        below_with_hysteresis(value, 64.0, 65.0, active=False) is expected_when_inactive
    )


@pytest.mark.parametrize("active", [True, False])
def test_a_band_of_zero_above_is_a_plain_comparison(active: bool) -> None:
    """An unconfigured band leaves the threshold behaving as written."""
    assert above_with_hysteresis(78.0, 78.0, 78.0, active=active) is True
    assert above_with_hysteresis(77.9, 78.0, 78.0, active=active) is False


@pytest.mark.parametrize("active", [True, False])
def test_a_band_of_zero_below_is_a_plain_comparison(active: bool) -> None:
    """An unconfigured band leaves the threshold behaving as written."""
    assert below_with_hysteresis(64.0, 64.0, 64.0, active=active) is True
    assert below_with_hysteresis(64.1, 64.0, 64.0, active=active) is False


@pytest.mark.parametrize("active", [True, False])
def test_an_inverted_band_above_is_rejected(active: bool) -> None:
    """A deactivation point above the activation point could never deactivate."""
    with pytest.raises(ValueError, match="deactivate_at <= activate_at"):
        above_with_hysteresis(78.0, 78.0, 79.0, active=active)


@pytest.mark.parametrize("active", [True, False])
def test_an_inverted_band_below_is_rejected(active: bool) -> None:
    """A deactivation point below the activation point could never deactivate."""
    with pytest.raises(ValueError, match="deactivate_at >= activate_at"):
        below_with_hysteresis(64.0, 64.0, 63.0, active=active)


@pytest.mark.parametrize("active", [True, False])
def test_a_non_numeric_reading_activates_nothing(active: bool) -> None:
    """A NaN reading neither activates a condition nor keeps an active one on.

    Deactivating discards the held state, so the value has to re-cross the
    activation boundary rather than the deactivation one. A non-finite reading
    must therefore be caught upstream and stop the tick, not reach here.
    """
    assert above_with_hysteresis(math.nan, 78.0, 77.0, active=active) is False
    assert below_with_hysteresis(math.nan, 64.0, 65.0, active=active) is False


def test_the_helpers_are_negative_safe() -> None:
    """Thresholds either side of zero compare as ordinary numbers."""
    assert above_with_hysteresis(-3.0, -5.0, -6.0, active=False) is True
    assert below_with_hysteresis(-7.0, -5.0, -4.0, active=False) is True

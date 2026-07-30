"""Tests for the window rules.

The per-rule checklist is: the condition holding, the condition absent, each
precondition failing on its own, every guard state, hysteresis in both
directions, a degraded answer that is never more aggressive than the full one,
and a group input only partly readable.

None of these rules is guarded and none reads an optional input, so the guard
and degraded rows do not apply. They are named rather than omitted, because a
later rule that skips a row it does have is the failure this checklist exists
to prevent.

All five close a window and share one advisory builder, so the shared
behaviour is asserted of all of them at once; what differs is what each reads
and when it decides that reading is a problem.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.room_advisor.models import (
    Action,
    Category,
    ConditionState,
    GroupObservation,
)
from custom_components.room_advisor.rules import RULES
from custom_components.room_advisor.rules.base import RuleOutcome, evaluate_rule
from custom_components.room_advisor.settings import RoomSettings, Threshold
from tests.rules import snapshots
from tests.rules.recording import RecordingObservations

AQI_LIMIT = 100.0
AQI_BAND = 10.0
COMFORT_FLOOR = 17.0
COMFORT_BAND = 0.5

SETTINGS = RoomSettings(
    thresholds={
        "outdoor_air_quality_limit": Threshold.rising(AQI_LIMIT, AQI_BAND),
        "indoor_comfort_floor": Threshold.falling(COMFORT_FLOOR, COMFORT_BAND),
    },
    durations={},
    activation_delays={},
)
NO_STATE = ConditionState(matching=frozenset(), active_since={})
_SOMETIME = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)

WINDOW_A = "binary_sensor.window_a"
WINDOW_B = "binary_sensor.window_b"


_UNCHANGED = object()
"""Stands for "leave the trigger firing", since `None` means unreadable."""


@dataclass(frozen=True, kw_only=True)
class CloseRule:
    """A rule that closes a window, and two readings either side of it."""

    id: str
    trigger: str
    firing: Any
    quiet: Any


CLOSE_RULES = [
    pytest.param(
        CloseRule(
            id="window.away_secure",
            trigger="away",
            firing=True,
            quiet=False,
        ),
        id="away_secure",
    ),
    pytest.param(
        CloseRule(
            id="window.rain_incoming",
            trigger="rain_risk",
            firing=True,
            quiet=False,
        ),
        id="rain_incoming",
    ),
    pytest.param(
        CloseRule(
            id="window.outdoor_air_quality",
            trigger="outdoor_air_quality",
            firing=AQI_LIMIT + 50,
            quiet=AQI_LIMIT - 50,
        ),
        id="outdoor_air_quality",
    ),
    pytest.param(
        CloseRule(
            id="window.room_too_cold",
            trigger="indoor_temperature",
            firing=COMFORT_FLOOR - 5,
            quiet=COMFORT_FLOOR + 5,
        ),
        id="room_too_cold",
    ),
    pytest.param(
        CloseRule(
            id="window.hvac_conflict",
            trigger="hvac_conditioning",
            firing=True,
            quiet=False,
        ),
        id="hvac_conflict",
    ),
]
"""Every rule that closes a window, with a reading either side of its decision."""


def _matching(rule_id: str) -> ConditionState:
    """Return a room in which this condition matched last evaluation."""
    return ConditionState(
        matching=frozenset({rule_id}), active_since={rule_id: _SOMETIME}
    )


def _room(
    close: CloseRule,
    *,
    reading: Any = _UNCHANGED,  # noqa: ANN401 - a reading is whatever its input is
    known_on: tuple[str, ...] = (WINDOW_A,),
    unusable: tuple[str, ...] = (),
) -> RecordingObservations:
    """Build a room whose trigger and window contacts read as asked."""
    return snapshots.snapshot(
        {close.trigger: close.firing if reading is _UNCHANGED else reading},
        {
            "window_contacts": snapshots.group(
                "window_contacts", known_on=known_on, unusable=unusable
            )
        },
    )


def _advise(
    rule_id: str,
    obs: RecordingObservations,
    state: ConditionState = NO_STATE,
) -> RuleOutcome:
    """Run one registered rule the way the runner does."""
    return evaluate_rule(RULES[rule_id], obs, SETTINGS, state)


@pytest.mark.parametrize("close", CLOSE_RULES)
def test_an_open_window_is_advised_closed_while_the_condition_holds(
    close: CloseRule,
) -> None:
    """The nominal case: advice attributed to this rule, naming this action."""
    outcome = _advise(close.id, _room(close))

    advisory = outcome.advisory
    assert advisory is not None
    assert advisory.rule_id == close.id
    assert advisory.category is Category.WINDOW
    assert advisory.action is Action.CLOSE
    assert advisory.reason_code == close.id.removeprefix("window.")


@pytest.mark.parametrize("close", CLOSE_RULES)
def test_no_advice_while_the_condition_does_not_hold(close: CloseRule) -> None:
    """An open window on its own is not something to correct."""
    outcome = _advise(close.id, _room(close, reading=close.quiet))

    assert outcome.evaluated
    assert outcome.advisory is None


@pytest.mark.parametrize("close", CLOSE_RULES)
def test_no_advice_while_every_window_is_closed(close: CloseRule) -> None:
    """There is nothing to advise closing."""
    outcome = _advise(close.id, _room(close, known_on=()))

    assert outcome.evaluated
    assert outcome.advisory is None


@pytest.mark.parametrize("close", CLOSE_RULES)
def test_no_advice_from_a_dead_contact_alone(close: CloseRule) -> None:
    """An unreadable contact is not a window known open.

    The asymmetry runs one way only: a window that cannot be read is not
    grounds for advice, it is merely not grounds against it.
    """
    outcome = _advise(close.id, _room(close, known_on=(), unusable=(WINDOW_B,)))

    assert outcome.evaluated
    assert outcome.advisory is None


@pytest.mark.parametrize("close", CLOSE_RULES)
def test_a_window_still_known_open_is_advised_on_despite_a_dead_contact(
    close: CloseRule,
) -> None:
    """Closing advice is given on partial information, deliberately.

    One contact being unreadable says nothing about the window that is
    plainly open, and withholding advice to shut it because a different
    sensor is broken would be the wrong way to be careful.
    """
    outcome = _advise(
        close.id, _room(close, known_on=(WINDOW_A,), unusable=(WINDOW_B,))
    )

    assert outcome.advisory is not None
    assert outcome.advisory.related_entities == (WINDOW_A,)


@pytest.mark.parametrize("close", CLOSE_RULES)
def test_the_rule_does_not_run_while_no_contact_can_be_read(close: CloseRule) -> None:
    """A room with nothing readable is waiting, not a room with nothing wrong.

    Reported as unevaluated so the room can say which input it is waiting on.
    """
    outcome = _advise(
        close.id, _room(close, known_on=(), unusable=(WINDOW_A, WINDOW_B))
    )

    assert not outcome.evaluated
    assert outcome.unreadable_inputs == ("window_contacts",)
    assert outcome.advisory is None


@pytest.mark.parametrize("close", CLOSE_RULES)
def test_the_rule_does_not_run_in_a_room_with_no_window_contacts(
    close: CloseRule,
) -> None:
    """A room with no contacts configured is a room this rule cannot serve."""
    obs = snapshots.snapshot(
        {close.trigger: close.firing},
        {
            "window_contacts": GroupObservation(
                key="window_contacts",
                configured=(),
                known_on=(),
                known_off=(),
                unusable=(),
            )
        },
    )

    outcome = _advise(close.id, obs)

    assert not outcome.evaluated
    assert outcome.unreadable_inputs == ("window_contacts",)


@pytest.mark.parametrize("close", CLOSE_RULES)
def test_the_rule_does_not_run_while_its_trigger_cannot_be_read(
    close: CloseRule,
) -> None:
    """A dead alarm panel is not proof that the house is occupied."""
    outcome = _advise(close.id, _room(close, reading=None))

    assert not outcome.evaluated
    assert outcome.unreadable_inputs == (close.trigger,)


@pytest.mark.parametrize("close", CLOSE_RULES)
def test_advice_names_the_open_windows_and_counts_them(close: CloseRule) -> None:
    """Consumers name the windows; the count is what the wording renders."""
    both = _advise(close.id, _room(close, known_on=(WINDOW_A, WINDOW_B)))
    one = _advise(close.id, _room(close, known_on=(WINDOW_B,)))

    assert both.advisory is not None
    assert both.advisory.related_entities == (WINDOW_A, WINDOW_B)
    assert both.advisory.reason_placeholders == {"window_count": 2}

    assert one.advisory is not None
    assert one.advisory.related_entities == (WINDOW_B,)
    assert one.advisory.reason_placeholders == {"window_count": 1}


@pytest.mark.parametrize("close", CLOSE_RULES)
def test_advice_names_the_entity_its_trigger_was_read_from(close: CloseRule) -> None:
    """Attributes carry no live values, so consumers are pointed at the source."""
    outcome = _advise(close.id, _room(close))

    advisory = outcome.advisory
    assert advisory is not None
    assert advisory.source_entities == {close.trigger: snapshots.SOURCES[close.trigger]}
    assert advisory.observations == {close.trigger: close.firing}


@pytest.mark.parametrize("close", CLOSE_RULES)
def test_advice_names_no_source_for_a_trigger_read_from_several_entities(
    close: CloseRule,
) -> None:
    """Several sources agreeing is an answer no single entity can be sent for."""
    outcome = _advise(close.id, snapshots.without_source(_room(close), close.trigger))

    advisory = outcome.advisory
    assert advisory is not None
    assert advisory.source_entities == {}


@pytest.mark.parametrize("close", CLOSE_RULES)
def test_the_rule_declares_the_inputs_it_reads_and_no_others(
    close: CloseRule,
) -> None:
    """Pinned as literal strings, since the runner matches on the stored key."""
    rule = RULES[close.id]

    assert rule.requires == (close.trigger, "window_contacts")
    assert rule.optional == ()
    assert rule.guards == ()


@pytest.mark.parametrize(
    ("rule_id", "delay"),
    [
        ("window.away_secure", timedelta(0)),
        ("window.rain_incoming", timedelta(0)),
        ("window.outdoor_air_quality", timedelta(seconds=30)),
        ("window.room_too_cold", timedelta(minutes=2)),
        ("window.hvac_conflict", timedelta(seconds=60)),
    ],
)
def test_each_rule_waits_as_long_as_its_cost_of_being_wrong(
    rule_id: str, delay: timedelta
) -> None:
    """The safety rules are immediate; the comfort ones sit out a fluctuation.

    Pinned here because a delay is a product decision that a room may override
    but a rule must have an opinion about.
    """
    assert RULES[rule_id].activation_delay == delay


@pytest.mark.parametrize(
    ("reading", "active", "advises"),
    [
        (AQI_LIMIT - 0.1, False, False),
        (AQI_LIMIT, False, True),
        (AQI_LIMIT - AQI_BAND, True, True),
        (AQI_LIMIT - AQI_BAND - 0.1, True, False),
    ],
)
def test_outdoor_air_quality_holds_its_answer_inside_the_band(
    reading: float, active: bool, advises: bool
) -> None:
    """Advice starts at the limit and stops a whole band below it.

    Without the band, a sensor hovering at the limit would advise, withdraw
    and advise again on consecutive readings.
    """
    close = CloseRule(
        id="window.outdoor_air_quality",
        trigger="outdoor_air_quality",
        firing=0,
        quiet=0,
    )
    state = _matching(close.id) if active else NO_STATE

    outcome = _advise(close.id, _room(close, reading=reading), state)

    assert (outcome.advisory is not None) is advises


@pytest.mark.parametrize(
    ("reading", "active", "advises"),
    [
        (COMFORT_FLOOR + 0.1, False, False),
        (COMFORT_FLOOR, False, True),
        (COMFORT_FLOOR + COMFORT_BAND, True, True),
        (COMFORT_FLOOR + COMFORT_BAND + 0.1, True, False),
    ],
)
def test_room_too_cold_holds_its_answer_inside_the_band(
    reading: float, active: bool, advises: bool
) -> None:
    """The mirror of the rising case: advice starts at the floor and stops above it."""
    close = CloseRule(
        id="window.room_too_cold",
        trigger="indoor_temperature",
        firing=0,
        quiet=0,
    )
    state = _matching(close.id) if active else NO_STATE

    outcome = _advise(close.id, _room(close, reading=reading), state)

    assert (outcome.advisory is not None) is advises


@pytest.mark.parametrize(
    ("rule_id", "trigger", "setting"),
    [
        (
            "window.outdoor_air_quality",
            "outdoor_air_quality",
            "outdoor_air_quality_limit",
        ),
        ("window.room_too_cold", "indoor_temperature", "indoor_comfort_floor"),
    ],
)
def test_a_threshold_rule_reaches_for_the_setting_it_is_named_for(
    rule_id: str, trigger: str, setting: str
) -> None:
    """A room missing a threshold is a programming error, and says so.

    Pinned as a literal name: the rule and the configuration that resolves it
    agree on a string, and nothing else checks that they still do.
    """
    unconfigured = RoomSettings(thresholds={}, durations={}, activation_delays={})
    close = CloseRule(id=rule_id, trigger=trigger, firing=0, quiet=0)

    with pytest.raises(KeyError, match=setting):
        evaluate_rule(RULES[rule_id], _room(close), unconfigured, NO_STATE)


def test_every_matching_rule_advises_on_the_same_open_window() -> None:
    """Several conditions can hold at once, and each is its own advisory.

    Precedence decides which is shown, and that is the selector's job; a rule
    does not suppress another rule.
    """
    obs = snapshots.snapshot(
        {
            "away": True,
            "rain_risk": True,
            "outdoor_air_quality": AQI_LIMIT + 50,
            "indoor_temperature": COMFORT_FLOOR - 5,
            "hvac_conditioning": True,
        },
        {"window_contacts": snapshots.group("window_contacts", known_on=(WINDOW_A,))},
    )

    assert all(
        _advise(rule.id, obs).advisory is not None
        for rule in RULES.for_category(Category.WINDOW)
    )

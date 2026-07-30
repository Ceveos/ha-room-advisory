"""Tests for the window rules.

The per-rule checklist is: the condition holding, the condition absent, each
precondition failing on its own, every guard state, hysteresis in both
directions, a degraded answer that is never more aggressive than the full one,
and a group input only partly readable.

Both rules here are immediate, unguarded and read no optional input, so the
guard, hysteresis and degraded rows do not apply to them. They are named
rather than omitted because a later rule that skips a row it does have is the
failure this checklist exists to prevent.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from custom_components.room_advisor.models import (
    Action,
    Category,
    ConditionState,
    GroupObservation,
)
from custom_components.room_advisor.rules import RULES
from custom_components.room_advisor.rules.base import Rule, RuleOutcome, evaluate_rule
from custom_components.room_advisor.settings import RoomSettings
from tests.rules import snapshots
from tests.rules.recording import RecordingObservations

SETTINGS = RoomSettings(thresholds={}, durations={}, activation_delays={})
NO_STATE = ConditionState(matching=frozenset(), active_since={})

WINDOW_A = "binary_sensor.window_a"
WINDOW_B = "binary_sensor.window_b"

CLOSE_RULES = [
    pytest.param("window.away_secure", "away", id="away_secure"),
    pytest.param("window.rain_incoming", "rain_risk", id="rain_incoming"),
]
"""The rules that close a window because of a condition outside the room."""


def _room(
    *,
    trigger: str,
    holding: bool | None = True,
    known_on: tuple[str, ...] = (WINDOW_A,),
    unusable: tuple[str, ...] = (),
) -> RecordingObservations:
    """Build a room whose trigger and window contacts read as asked."""
    return snapshots.snapshot(
        {trigger: holding},
        {
            "window_contacts": snapshots.group(
                "window_contacts", known_on=known_on, unusable=unusable
            )
        },
    )


def _advise(rule_id: str, obs: RecordingObservations) -> RuleOutcome:
    """Run one registered rule the way the runner does."""
    return evaluate_rule(RULES[rule_id], obs, SETTINGS, NO_STATE)


@pytest.mark.parametrize(("rule_id", "trigger"), CLOSE_RULES)
def test_an_open_window_is_advised_closed_while_the_condition_holds(
    rule_id: str, trigger: str
) -> None:
    """The nominal case: advice attributed to this rule, naming this action."""
    outcome = _advise(rule_id, _room(trigger=trigger))

    advisory = outcome.advisory
    assert advisory is not None
    assert advisory.rule_id == rule_id
    assert advisory.category is Category.WINDOW
    assert advisory.action is Action.CLOSE
    assert advisory.reason_code == rule_id.removeprefix("window.")


@pytest.mark.parametrize(("rule_id", "trigger"), CLOSE_RULES)
def test_no_advice_while_the_condition_does_not_hold(
    rule_id: str, trigger: str
) -> None:
    """An open window on its own is not something to correct."""
    outcome = _advise(rule_id, _room(trigger=trigger, holding=False))

    assert outcome.evaluated
    assert outcome.advisory is None


@pytest.mark.parametrize(("rule_id", "trigger"), CLOSE_RULES)
def test_no_advice_while_every_window_is_closed(rule_id: str, trigger: str) -> None:
    """There is nothing to advise closing."""
    outcome = _advise(rule_id, _room(trigger=trigger, known_on=()))

    assert outcome.evaluated
    assert outcome.advisory is None


@pytest.mark.parametrize(("rule_id", "trigger"), CLOSE_RULES)
def test_no_advice_from_a_dead_contact_alone(rule_id: str, trigger: str) -> None:
    """An unreadable contact is not a window known open.

    The asymmetry runs one way only: a window that cannot be read is not
    grounds for advice, it is merely not grounds against it.
    """
    outcome = _advise(
        rule_id, _room(trigger=trigger, known_on=(), unusable=(WINDOW_B,))
    )

    assert outcome.evaluated
    assert outcome.advisory is None


@pytest.mark.parametrize(("rule_id", "trigger"), CLOSE_RULES)
def test_a_window_still_known_open_is_advised_on_despite_a_dead_contact(
    rule_id: str, trigger: str
) -> None:
    """Closing advice is given on partial information, deliberately.

    One contact being unreadable says nothing about the window that is
    plainly open, and withholding advice to shut it because a different
    sensor is broken would be the wrong way to be careful.
    """
    outcome = _advise(
        rule_id, _room(trigger=trigger, known_on=(WINDOW_A,), unusable=(WINDOW_B,))
    )

    assert outcome.advisory is not None
    assert outcome.advisory.related_entities == (WINDOW_A,)


@pytest.mark.parametrize(("rule_id", "trigger"), CLOSE_RULES)
def test_the_rule_does_not_run_while_no_contact_can_be_read(
    rule_id: str, trigger: str
) -> None:
    """A room with nothing readable is waiting, not a room with nothing wrong.

    Reported as unevaluated so the room can say which input it is waiting on.
    """
    outcome = _advise(
        rule_id, _room(trigger=trigger, known_on=(), unusable=(WINDOW_A, WINDOW_B))
    )

    assert not outcome.evaluated
    assert outcome.unreadable_inputs == ("window_contacts",)
    assert outcome.advisory is None


@pytest.mark.parametrize(("rule_id", "trigger"), CLOSE_RULES)
def test_the_rule_does_not_run_in_a_room_with_no_window_contacts(
    rule_id: str, trigger: str
) -> None:
    """A room with no contacts configured is a room this rule cannot serve."""
    obs = snapshots.snapshot(
        {trigger: True},
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

    outcome = _advise(rule_id, obs)

    assert not outcome.evaluated
    assert outcome.unreadable_inputs == ("window_contacts",)


@pytest.mark.parametrize(("rule_id", "trigger"), CLOSE_RULES)
def test_the_rule_does_not_run_while_its_trigger_cannot_be_read(
    rule_id: str, trigger: str
) -> None:
    """A dead alarm panel is not proof that the house is occupied."""
    outcome = _advise(rule_id, _room(trigger=trigger, holding=None))

    assert not outcome.evaluated
    assert outcome.unreadable_inputs == (trigger,)


@pytest.mark.parametrize(("rule_id", "trigger"), CLOSE_RULES)
def test_advice_names_the_open_windows_and_counts_them(
    rule_id: str, trigger: str
) -> None:
    """Consumers name the windows; the count is what the wording renders."""
    both = _advise(rule_id, _room(trigger=trigger, known_on=(WINDOW_A, WINDOW_B)))
    one = _advise(rule_id, _room(trigger=trigger, known_on=(WINDOW_B,)))

    assert both.advisory is not None
    assert both.advisory.related_entities == (WINDOW_A, WINDOW_B)
    assert both.advisory.reason_placeholders == {"window_count": 2}

    assert one.advisory is not None
    assert one.advisory.related_entities == (WINDOW_B,)
    assert one.advisory.reason_placeholders == {"window_count": 1}


@pytest.mark.parametrize(("rule_id", "trigger"), CLOSE_RULES)
def test_advice_names_the_entity_its_trigger_was_read_from(
    rule_id: str, trigger: str
) -> None:
    """Attributes carry no live values, so consumers are pointed at the source."""
    outcome = _advise(rule_id, _room(trigger=trigger))

    advisory = outcome.advisory
    assert advisory is not None
    assert advisory.source_entities == {trigger: snapshots.SOURCES[trigger]}
    assert advisory.observations == {trigger: True}


@pytest.mark.parametrize(("rule_id", "trigger"), CLOSE_RULES)
def test_advice_names_no_source_for_a_trigger_read_from_several_entities(
    rule_id: str, trigger: str
) -> None:
    """Several sources agreeing is an answer no single entity can be sent for."""
    obs = snapshots.snapshot(
        {trigger: True},
        {"window_contacts": snapshots.group("window_contacts", known_on=(WINDOW_A,))},
    )
    obs = snapshots.without_source(obs, trigger)

    outcome = _advise(rule_id, obs)

    advisory = outcome.advisory
    assert advisory is not None
    assert advisory.source_entities == {}


@pytest.mark.parametrize(("rule_id", "trigger"), CLOSE_RULES)
def test_the_rule_declares_the_inputs_it_reads_and_no_others(
    rule_id: str, trigger: str
) -> None:
    """Pinned as literal strings, since the runner matches on the stored key."""
    rule: Rule = RULES[rule_id]

    assert rule.requires == (trigger, "window_contacts")
    assert rule.optional == ()
    assert rule.guards == ()


@pytest.mark.parametrize(("rule_id", "trigger"), CLOSE_RULES)
def test_closing_advice_is_immediate(rule_id: str, trigger: str) -> None:
    """A delay on advice to shut a window has no upside worth the wait."""
    assert RULES[rule_id].activation_delay == timedelta(0)
    assert trigger in RULES[rule_id].requires


def test_away_and_rain_advise_separately_on_the_same_open_window() -> None:
    """Both conditions can hold at once, and each is its own advisory.

    Precedence decides which of the two is shown, and that is the selector's
    job; a rule does not suppress another rule.
    """
    obs = snapshots.snapshot(
        {"away": True, "rain_risk": True},
        {"window_contacts": snapshots.group("window_contacts", known_on=(WINDOW_A,))},
    )

    assert _advise("window.away_secure", obs).advisory is not None
    assert _advise("window.rain_incoming", obs).advisory is not None

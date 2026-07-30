"""The contract every registered rule keeps, whichever category it belongs to.

Parametrised over the registry rather than written per rule, so a rule added
later is held to all of this without anyone remembering to. The behaviour of
an individual rule is tested in its category's module; what is checked here is
that it is declared honestly.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest
from _pytest.mark import ParameterSet

from custom_components.room_advisor.models import (
    Action,
    Category,
    ConditionState,
    UnusableReason,
)
from custom_components.room_advisor.observations import OBSERVATION_KEYS
from custom_components.room_advisor.rules import RULES
from custom_components.room_advisor.rules.base import Rule
from custom_components.room_advisor.settings import THRESHOLD_KEYS
from tests.rules import snapshots
from tests.rules.recording import RecordingObservations

NO_STATE = ConditionState(matching=frozenset(), active_since={})

_CATEGORY_INPUTS = {
    Category.WINDOW: frozenset({"window_contacts"}),
    Category.FAN: frozenset({"fan"}),
    Category.LIGHT: frozenset({"lights"}),
}
"""The inputs each category owns, which no other category's rules may read."""

_OPENING = frozenset({Action.OPEN, Action.TURN_ON})
"""The actions that put a room into a state it was not already in."""


def _every_rule() -> list[ParameterSet]:
    """Every registered rule, named by its id in test output."""
    return [pytest.param(rule, id=rule.id) for rule in RULES.all_rules()]


def _rooms_reaching_every_branch(rule: Rule) -> Iterator[RecordingObservations]:
    """Rooms enough to take a rule down each way it can go.

    Beyond the readings and windows `every_room` varies, each input the rule
    does not require is withheld in turn, once as an input the room was never
    given and once as one whose sensor has died. A rule that reads something
    only when an optional input is absent is answering in degraded mode, and
    that answer would otherwise never be run.
    """
    yield from snapshots.every_room()
    for key in snapshots.READINGS:
        if key in rule.requires:
            continue
        for reason in (UnusableReason.NOT_CONFIGURED, UnusableReason.UNAVAILABLE):
            yield from snapshots.every_room(missing={key: reason})


def test_the_window_rules_are_published_in_this_order() -> None:
    """Precedence is registration order, so the order here is the product.

    Pinned as literal strings: reordering the classes in `window.py` changes
    which advice a room shows when two conditions hold at once, and that is a
    decision that should have to be made in this file too.
    """
    assert [rule.id for rule in RULES.for_category(Category.WINDOW)] == [
        "window.away_secure",
        "window.rain_incoming",
        "window.outdoor_air_quality",
        "window.room_too_cold",
        "window.hvac_conflict",
    ]


def test_no_rule_reads_an_input_the_observation_layer_cannot_supply() -> None:
    """A mistyped key would disable a rule in every house, silently.

    The runner treats an input a room lacks as "this rule does not apply
    here", which is right for a house with no CO₂ sensor and indistinguishable
    from a typo without this check.
    """
    assert RULES.undeclared_inputs(OBSERVATION_KEYS) == frozenset()


@pytest.mark.parametrize("rule", _every_rule())
def test_a_rule_is_named_for_its_category_and_reason(rule: Rule) -> None:
    """The id is `<category>.<reason_code>` and the parts are not empty."""
    assert rule.id == f"{rule.category.value}.{rule.reason_code}"
    assert rule.reason_code


@pytest.mark.parametrize("rule", _every_rule())
def test_a_rule_declares_a_delay_that_is_not_negative(rule: Rule) -> None:
    """A negative delay would publish advice before its condition held."""
    assert rule.activation_delay >= timedelta(0)


@pytest.mark.parametrize("rule", _every_rule())
def test_a_rule_reads_only_the_inputs_it_declared(rule: Rule) -> None:
    """An undeclared read goes quiet in the houses that lack that sensor.

    The runner waits only on declared inputs, so a rule reading one it never
    named is called with that input unusable, and either raises or answers
    from a value it should not have had.

    Checked over every room in `every_room`, because a read a rule makes only
    once a reading is extreme is the shape of most of the rules there are.
    """
    for obs in _rooms_reaching_every_branch(rule):
        rule.evaluate(obs, snapshots.ANY_SETTINGS, NO_STATE)
        assert obs.undeclared_reads(rule) == frozenset()


@pytest.mark.parametrize("rule", _every_rule())
def test_a_rule_consults_everything_it_asked_the_runner_to_wait_for(
    rule: Rule,
) -> None:
    """A declared input a rule never reads costs advice and buys nothing.

    A required input the rule ignores makes the runner withhold it from every
    house that lacks that sensor, for no benefit. A declared guard that is
    never consulted is a veto that does not veto, which is the failure a
    copied rule is most likely to carry.

    `optional` is exempt: an optional input exists to be read down one branch
    and not the other.
    """
    read: set[str] = set()
    for obs in snapshots.every_room():
        rule.evaluate(obs, snapshots.ANY_SETTINGS, NO_STATE)
        read |= obs.keys_read

    assert {*rule.requires, *rule.guards} <= read


@pytest.mark.parametrize("rule", _every_rule())
def test_a_rule_reads_no_other_category_s_inputs(rule: Rule) -> None:
    """Categories are published separately and must be decided separately.

    A window rule that consulted the fan would make window advice change when
    the fan was switched, which no consumer of window advice would predict.
    """
    declared = {*rule.requires, *rule.optional, *rule.guards}
    foreign = frozenset[str]().union(
        *(
            keys
            for category, keys in _CATEGORY_INPUTS.items()
            if category is not rule.category
        )
    )
    assert declared & foreign == frozenset()


@pytest.mark.parametrize("rule", _every_rule())
def test_a_rule_asks_only_for_settings_a_room_can_be_given(rule: Rule) -> None:
    """A threshold a room does not carry raises when the rule is first run.

    Rules reach for settings by name, and `RoomSettings` raises for a name it
    does not hold. Nothing else compares the names rules ask for against the
    names configuration supplies, so a mistyped one would take down every
    evaluation in the house that first crossed it.
    """
    asked: set[str] = set()
    for obs in snapshots.every_room():
        settings = snapshots.recording_settings()
        rule.evaluate(obs, settings, NO_STATE)
        asked |= settings.thresholds_asked

    assert asked <= THRESHOLD_KEYS


@pytest.mark.parametrize("rule", _every_rule())
def test_withholding_an_optional_input_never_creates_advice(rule: Rule) -> None:
    """A degraded answer is never bolder than the full one.

    A rule that reads an optional input owns the answer it gives without one.
    That answer may be more cautious, and usually is; what it may never be is
    advice the same room would not have been given had the input been there.
    Information going missing is not a reason to act.

    Compared room by room, so the two answers differ in nothing but the one
    input.
    """
    for key in rule.optional:
        for reason in (UnusableReason.NOT_CONFIGURED, UnusableReason.UNAVAILABLE):
            for informed, degraded in zip(
                snapshots.every_room(levels=snapshots.SWEEP),
                snapshots.every_room(missing={key: reason}, levels=snapshots.SWEEP),
                strict=True,
            ):
                if rule.evaluate(degraded, snapshots.ANY_SETTINGS, NO_STATE) is None:
                    continue
                assert (
                    rule.evaluate(informed, snapshots.ANY_SETTINGS, NO_STATE)
                    is not None
                )


@pytest.mark.parametrize("rule", _every_rule())
def test_a_rule_never_advises_opening_while_a_guard_cannot_be_read(
    rule: Rule,
) -> None:
    """A guard that is merely read is a guard that does not guard.

    A configured guard the room cannot read withholds advice to open exactly
    as a blocking one does: advising a window open into rain the integration
    could not see is the failure guards exist to prevent. An unconfigured
    guard is skipped instead, which is the user's own choice and is covered by
    every other room here.
    """
    for key in rule.guards:
        for obs in snapshots.every_room(missing={key: UnusableReason.UNAVAILABLE}):
            advisory = rule.evaluate(obs, snapshots.ANY_SETTINGS, NO_STATE)
            assert advisory is None or advisory.action not in _OPENING


@pytest.mark.parametrize("rule", _every_rule())
def test_a_rule_never_advises_opening_while_a_member_cannot_be_read(
    rule: Rule,
) -> None:
    """Advice to open is never given on partial information.

    A closing rule needs one window known open, and a contact it cannot read
    neither triggers it nor holds it back. An opening rule is the opposite:
    every member must be readable and shut, because the one contact that
    cannot be read is the one that would make opening wrong.

    Held here rather than per rule so that a rule copied from a closing one
    and changed to open cannot keep the closing asymmetry.
    """
    for obs in snapshots.every_room(dead_member=True):
        advisory = rule.evaluate(obs, snapshots.ANY_SETTINGS, NO_STATE)
        assert advisory is None or advisory.action not in _OPENING


def test_the_full_room_offers_exactly_the_observation_vocabulary() -> None:
    """The room these tests are written against is the room rules will meet.

    Without this, a key added to the observation layer would never appear in
    any rule test, and a key removed from it would go on being tested here
    long after no room could supply it.
    """
    room = snapshots.snapshot()
    assert set(room) | set(room.groups) == set(OBSERVATION_KEYS)
    assert room.usable(*OBSERVATION_KEYS)

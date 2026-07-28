"""Tests for the core data structures.

These run without a Home Assistant instance, which is the property that makes
them the inner development loop for every layer built on top.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from custom_components.room_advisor.models import (
    Action,
    Advisory,
    Category,
    ConditionState,
    GroupObservation,
    GuardState,
    Observation,
    Observations,
    UnusableObservationError,
    UnusableReason,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _group(
    *,
    on: tuple[str, ...] = (),
    off: tuple[str, ...] = (),
    unusable: tuple[str, ...] = (),
) -> GroupObservation:
    """Build a group whose configuration is implied by its members."""
    return GroupObservation(
        key="window_contacts",
        configured=(*on, *off, *unusable),
        known_on=on,
        known_off=off,
        unusable=unusable,
    )


# The published vocabulary


def test_action_values_are_the_published_states() -> None:
    """Advice states are the strings consumers match on."""
    assert [action.value for action in Action] == [
        "open",
        "close",
        "turn_on",
        "turn_off",
        "none",
    ]


def test_category_values_are_the_published_names() -> None:
    """Categories name the entities, so their values are a contract too."""
    assert [category.value for category in Category] == ["window", "fan", "light"]


def test_unusable_reasons_are_the_documented_set() -> None:
    """Reasons appear in diagnostics and must not drift silently."""
    assert {reason.value for reason in UnusableReason} == {
        "not_configured",
        "unavailable",
        "unknown",
        "unconvertible",
        "not_yet_seen",
        "source_offline",
    }


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        (Category.WINDOW, {Action.OPEN, Action.CLOSE}),
        (Category.FAN, {Action.TURN_ON, Action.TURN_OFF}),
        (Category.LIGHT, {Action.TURN_OFF}),
    ],
)
def test_each_category_advises_its_own_actions(
    category: Category, expected: set[Action]
) -> None:
    """Each category advises only the actions its entity publishes."""
    assert category.advisable_actions == expected


def test_no_category_may_advise_none() -> None:
    """`none` is the absence of advice, so no advisory carries it."""
    for category in Category:
        assert Action.NONE not in category.advisable_actions


# Observation


def test_a_reading_is_usable() -> None:
    """A reading carries its value, unit and source."""
    observation = Observation.reading(
        "indoor_temperature", 21.5, unit="°C", source_entity_id="sensor.office"
    )

    assert observation.usable
    assert observation.value == 21.5
    assert observation.unit == "°C"
    assert observation.unusable_reason is None
    assert observation.source_entity_id == "sensor.office"


def test_a_missing_input_is_unusable_and_keeps_its_reason() -> None:
    """The reason survives, because the guard model turns on it."""
    observation = Observation.missing("outdoor_humidity", UnusableReason.UNAVAILABLE)

    assert not observation.usable
    assert observation.unusable_reason is UnusableReason.UNAVAILABLE
    assert observation.value is None


def test_a_reading_of_false_is_still_usable() -> None:
    """Usability is not truthiness; a guard reading `false` was read."""
    assert Observation.reading("rain_incoming", value=False).usable


def test_an_unusable_observation_may_not_carry_a_value() -> None:
    """A value nobody may read is a stale value waiting to be read."""
    with pytest.raises(ValueError, match="must not carry a value"):
        Observation(
            key="indoor_temperature",
            value=21.5,
            unit=None,
            unusable_reason=UnusableReason.UNAVAILABLE,
            source_entity_id=None,
        )


def test_an_observation_cannot_be_mutated() -> None:
    """Observations are a snapshot of one moment."""
    observation = Observation.reading("indoor_temperature", 21.5)

    with pytest.raises(dataclasses.FrozenInstanceError):
        observation.value = 22.0  # type: ignore[misc]


# GroupObservation


def test_group_members_must_partition_the_configuration() -> None:
    """Every configured member is known on, known off, or unusable."""
    with pytest.raises(ValueError, match="partition"):
        GroupObservation(
            key="window_contacts",
            configured=("binary_sensor.a", "binary_sensor.b"),
            known_on=("binary_sensor.a",),
            known_off=(),
            unusable=(),
        )


def test_a_group_member_may_not_appear_twice() -> None:
    """A member counted twice would make the availability tests lie."""
    with pytest.raises(ValueError, match="partition"):
        GroupObservation(
            key="window_contacts",
            configured=("binary_sensor.a",),
            known_on=("binary_sensor.a",),
            known_off=("binary_sensor.a",),
            unusable=(),
        )


def test_a_group_member_may_not_be_unconfigured() -> None:
    """A member that is not configured cannot have a reading."""
    with pytest.raises(ValueError, match="partition"):
        GroupObservation(
            key="window_contacts",
            configured=("binary_sensor.a",),
            known_on=("binary_sensor.a",),
            known_off=("binary_sensor.b",),
            unusable=(),
        )


@pytest.mark.parametrize(
    ("group", "usable", "any_known_on", "all_usable_and_off"),
    [
        (_group(), False, False, False),
        (_group(off=("a",)), True, False, True),
        (_group(on=("a",)), True, True, False),
        (_group(on=("a",), off=("b",)), True, True, False),
        (_group(unusable=("a",)), False, False, False),
        (_group(off=("a",), unusable=("b",)), True, False, False),
        (_group(on=("a",), unusable=("b",)), True, True, False),
        (_group(unusable=("a", "b")), False, False, False),
    ],
    ids=[
        "unconfigured",
        "one closed",
        "one open",
        "one open one closed",
        "only member unreadable",
        "one closed one unreadable",
        "one open one unreadable",
        "all unreadable",
    ],
)
def test_partial_availability(
    group: GroupObservation,
    usable: bool,
    any_known_on: bool,
    all_usable_and_off: bool,
) -> None:
    """The three group tests across every mix of member states."""
    assert group.usable is usable
    assert group.any_known_on is any_known_on
    assert group.all_usable_and_off is all_usable_and_off


def test_closing_advice_survives_a_dead_contact() -> None:
    """One unreadable contact must not silence advice about an open one."""
    group = _group(on=("binary_sensor.left",), unusable=("binary_sensor.right",))

    assert group.usable
    assert group.any_known_on


def test_opening_advice_does_not_survive_a_dead_contact() -> None:
    """Advice to open needs every contact readable and closed."""
    group = _group(off=("binary_sensor.left",), unusable=("binary_sensor.right",))

    assert not group.all_usable_and_off


# The Observations mapping


def test_indexing_yields_the_observation_even_when_unusable() -> None:
    """Diagnostics explains a room from the inputs it could not use."""
    unusable = Observation.missing("outdoor_humidity", UnusableReason.UNKNOWN)
    observations = Observations({"outdoor_humidity": unusable})

    assert observations["outdoor_humidity"] is unusable


def test_observations_iterate_and_size() -> None:
    """The snapshot behaves as an ordinary mapping."""
    observations = Observations(
        {
            "indoor_temperature": Observation.reading("indoor_temperature", 21.5),
            "outdoor_temperature": Observation.reading("outdoor_temperature", 9.0),
        }
    )

    assert set(observations) == {"indoor_temperature", "outdoor_temperature"}
    assert len(observations) == 2
    assert "indoor_temperature" in observations


def test_get_keeps_its_usual_meaning() -> None:
    """`get` returns the observation; `get_value` applies usability."""
    observation = Observation.reading("indoor_temperature", 21.5)
    observations = Observations({"indoor_temperature": observation})

    assert observations.get("indoor_temperature") is observation
    assert observations.get("absent") is None


def test_groups_are_not_part_of_the_mapping() -> None:
    """Groups are reached through `group`, since they are not observations."""
    observations = Observations(groups={"window_contacts": _group(off=("a",))})

    assert len(observations) == 0
    assert "window_contacts" not in observations
    assert observations.group("window_contacts").usable


def test_groups_cannot_be_mutated_through_the_accessor() -> None:
    """A rule cannot rewrite the snapshot it was handed."""
    observations = Observations(groups={"window_contacts": _group(off=("a",))})

    with pytest.raises(TypeError):
        observations.groups["window_contacts"] = _group()  # type: ignore[index]


def test_an_unknown_group_raises() -> None:
    """Asking for a group a room never built is a programming error."""
    with pytest.raises(KeyError):
        Observations().group("window_contacts")


# Usability


def test_usable_reports_on_several_keys_at_once() -> None:
    """The runner gates a rule on all of its required inputs."""
    observations = Observations(
        {
            "indoor_temperature": Observation.reading("indoor_temperature", 21.5),
            "outdoor_temperature": Observation.missing(
                "outdoor_temperature", UnusableReason.UNAVAILABLE
            ),
        }
    )

    assert observations.usable("indoor_temperature")
    assert not observations.usable("outdoor_temperature")
    assert not observations.usable("indoor_temperature", "outdoor_temperature")


def test_no_keys_is_vacuously_usable() -> None:
    """A rule requiring nothing is never gated."""
    assert Observations().usable()


def test_a_group_key_uses_the_group_test() -> None:
    """For a multi-entity input, usable means at least one member readable."""
    observations = Observations(
        groups={
            "window_contacts": _group(off=("a",), unusable=("b",)),
            "lights": _group(unusable=("c",)),
        }
    )

    assert observations.usable("window_contacts")
    assert not observations.usable("lights")


def test_an_unknown_key_is_not_usable() -> None:
    """An input a room never built cannot be read."""
    assert not Observations().usable("never_built")


# Reading values


def test_value_returns_a_usable_reading() -> None:
    """The ordinary path."""
    observations = Observations(
        {"indoor_temperature": Observation.reading("indoor_temperature", 21.5)}
    )

    assert observations.value("indoor_temperature") == 21.5


def test_reading_an_unusable_value_raises_with_the_reason() -> None:
    """A rule that skipped its own gate fails loudly rather than seeing None."""
    observations = Observations(
        {
            "outdoor_humidity": Observation.missing(
                "outdoor_humidity", UnusableReason.SOURCE_OFFLINE
            )
        }
    )

    with pytest.raises(UnusableObservationError) as caught:
        observations.value("outdoor_humidity")

    assert caught.value.key == "outdoor_humidity"
    assert caught.value.reason is UnusableReason.SOURCE_OFFLINE
    assert "source_offline" in str(caught.value)


def test_reading_an_undeclared_key_raises() -> None:
    """Reading an input the room never built is a programming error."""
    with pytest.raises(KeyError):
        Observations().value("never_declared")


@pytest.mark.parametrize(
    ("key", "expected"),
    [("indoor_temperature", 21.5), ("outdoor_humidity", None), ("absent", None)],
)
def test_get_value_falls_back_quietly(key: str, expected: float | None) -> None:
    """Optional inputs are read without a gate."""
    observations = Observations(
        {
            "indoor_temperature": Observation.reading("indoor_temperature", 21.5),
            "outdoor_humidity": Observation.missing(
                "outdoor_humidity", UnusableReason.UNKNOWN
            ),
        }
    )

    assert observations.get_value(key) == expected


def test_get_value_takes_an_explicit_default() -> None:
    """The fallback is the caller's to choose."""
    assert Observations().get_value("absent", 0.0) == 0.0


# Guards


@pytest.mark.parametrize(
    ("observation", "expected"),
    [
        (
            Observation.missing("rain_incoming", UnusableReason.NOT_CONFIGURED),
            GuardState.NOT_CONFIGURED,
        ),
        (Observation.reading("rain_incoming", value=False), GuardState.SATISFIED),
        (Observation.reading("rain_incoming", value=True), GuardState.BLOCKING),
        (
            Observation.missing("rain_incoming", UnusableReason.UNAVAILABLE),
            GuardState.UNUSABLE,
        ),
        (
            Observation.missing("rain_incoming", UnusableReason.SOURCE_OFFLINE),
            GuardState.UNUSABLE,
        ),
    ],
    ids=["unconfigured", "clear", "blocking", "unavailable", "offline"],
)
def test_guard_states(observation: Observation, expected: GuardState) -> None:
    """A guard reports four states, not a boolean."""
    observations = Observations({"rain_incoming": observation})

    assert observations.guard("rain_incoming") is expected


def test_a_mistyped_guard_key_raises_rather_than_being_skipped() -> None:
    """An unknown guard must not read as an absent one, which is skipped."""
    with pytest.raises(KeyError):
        Observations().guard("rian_incoming")


def test_guard_when_decides_what_a_reading_means() -> None:
    """Numeric guards supply their own blocking test."""
    observations = Observations(
        {
            "outdoor_dew_point": Observation.reading("outdoor_dew_point", 18.0),
            "outdoor_dew_point_low": Observation.reading("outdoor_dew_point_low", 12.0),
        }
    )

    def above_ceiling(value: float) -> bool:
        return value > 16.0

    assert (
        observations.guard_when("outdoor_dew_point", above_ceiling)
        is GuardState.BLOCKING
    )
    assert (
        observations.guard_when("outdoor_dew_point_low", above_ceiling)
        is GuardState.SATISFIED
    )


def test_guard_when_still_distinguishes_unconfigured_from_broken() -> None:
    """Degraded mode and withheld advice differ by this one field."""
    observations = Observations(
        {
            "unconfigured": Observation.missing(
                "unconfigured", UnusableReason.NOT_CONFIGURED
            ),
            "broken": Observation.missing("broken", UnusableReason.UNAVAILABLE),
        }
    )

    def never(_value: float) -> bool:
        return False

    assert observations.guard_when("unconfigured", never) is GuardState.NOT_CONFIGURED
    assert observations.guard_when("broken", never) is GuardState.UNUSABLE


# Advisory


def test_an_advisory_carries_a_reason_code_rather_than_a_rendered_string() -> None:
    """Rendering belongs to the publisher, which has the translations."""
    advisory = Advisory(
        rule_id="window.passive_cooling",
        category=Category.WINDOW,
        action=Action.OPEN,
        reason_code="passive_cooling",
        reason_placeholders={"advantage": 4.0},
    )

    assert advisory.reason_code == "passive_cooling"
    assert advisory.reason_placeholders["advantage"] == 4.0


@pytest.mark.parametrize(
    ("category", "action"),
    [
        (Category.WINDOW, Action.TURN_ON),
        (Category.FAN, Action.OPEN),
        (Category.LIGHT, Action.TURN_ON),
        (Category.WINDOW, Action.NONE),
    ],
    ids=["window cannot switch", "fan cannot open", "light cannot be lit", "none"],
)
def test_a_category_rejects_an_action_it_cannot_advise(
    category: Category, action: Action
) -> None:
    """An entity may only ever publish one of its declared options."""
    with pytest.raises(ValueError, match="cannot advise"):
        Advisory(
            rule_id="rule",
            category=category,
            action=action,
            reason_code="reason",
        )


def test_identity_is_the_room_and_the_rule() -> None:
    """Identity is exactly the room subentry id and the rule id."""
    advisory = Advisory(
        rule_id="window.rain_incoming",
        category=Category.WINDOW,
        action=Action.CLOSE,
        reason_code="rain_incoming",
    )

    assert advisory.identity_in("01JABC") == ("01JABC", "window.rain_incoming")


def test_identity_ignores_everything_that_changes_during_its_life() -> None:
    """A tenth of a degree, or a second window, must not restart a timer."""

    def build(temperature: float, entities: tuple[str, ...]) -> Advisory:
        return Advisory(
            rule_id="window.passive_cooling",
            category=Category.WINDOW,
            action=Action.OPEN,
            reason_code="passive_cooling",
            reason_placeholders={"temperature": temperature},
            related_entities=entities,
            observations={"indoor_temperature": temperature},
        )

    first = build(25.6, ("binary_sensor.left",))
    second = build(25.7, ("binary_sensor.left", "binary_sensor.right"))

    assert first.identity_in("room") == second.identity_in("room")


def test_an_advisory_mapping_cannot_be_changed_behind_its_back() -> None:
    """The snapshot is frozen on publish and must stay that way."""
    placeholders = {"advantage": 4.0}
    advisory = Advisory(
        rule_id="window.passive_cooling",
        category=Category.WINDOW,
        action=Action.OPEN,
        reason_code="passive_cooling",
        reason_placeholders=placeholders,
    )

    placeholders["advantage"] = 99.0

    assert advisory.reason_placeholders["advantage"] == 4.0
    with pytest.raises(TypeError):
        advisory.reason_placeholders["advantage"] = 99.0  # type: ignore[index]


def test_an_advisory_defaults_to_empty_context() -> None:
    """A rule with nothing to add supplies nothing."""
    advisory = Advisory(
        rule_id="light.lights_left_on",
        category=Category.LIGHT,
        action=Action.TURN_OFF,
        reason_code="lights_left_on",
    )

    assert advisory.related_entities == ()
    assert dict(advisory.reason_placeholders) == {}
    assert dict(advisory.source_entities) == {}
    assert dict(advisory.observations) == {}


# ConditionState


def test_condition_state_reports_which_conditions_matched() -> None:
    """Hysteresis asks whether the condition itself was matching."""
    state = ConditionState(
        matching=frozenset({"window.passive_cooling"}),
        active_since={"window.passive_cooling": NOW},
    )

    assert state.is_active("window.passive_cooling")
    assert not state.is_active("window.co2_ventilation")


def test_an_empty_condition_state_matches_nothing() -> None:
    """The state at the first evaluation after a reload."""
    assert not ConditionState(matching=frozenset(), active_since={}).is_active("any")


def test_a_matching_condition_must_have_a_start_time() -> None:
    """Timings and matches describe the same set of conditions."""
    with pytest.raises(ValueError, match="active_since"):
        ConditionState(matching=frozenset({"window.passive_cooling"}), active_since={})


def test_a_start_time_must_belong_to_a_matching_condition() -> None:
    """A condition that stopped matching drops its timing with it."""
    with pytest.raises(ValueError, match="active_since"):
        ConditionState(
            matching=frozenset(),
            active_since={"window.passive_cooling": NOW},
        )


def test_condition_timings_cannot_be_changed_behind_its_back() -> None:
    """The state handed to a rule is the state that was evaluated."""
    timings = {"window.passive_cooling": NOW}
    state = ConditionState(
        matching=frozenset({"window.passive_cooling"}), active_since=timings
    )

    timings["window.passive_cooling"] = datetime(2020, 1, 1, tzinfo=UTC)

    assert state.active_since["window.passive_cooling"] == NOW

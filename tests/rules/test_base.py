"""Tests for the rule protocol, the registry, and the runner."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from custom_components.room_advisor.models import (
    Action,
    Advisory,
    Category,
    ConditionState,
    GroupObservation,
    Observation,
    Observations,
    UnusableReason,
)
from custom_components.room_advisor.rules.base import (
    RuleContractError,
    RuleDefinitionError,
    RuleRegistry,
    evaluate_all,
    evaluate_rule,
)
from custom_components.room_advisor.settings import RoomSettings
from tests.rules.recording import RecordingObservations

if TYPE_CHECKING:
    from custom_components.room_advisor.rules.base import Rule

SETTINGS = RoomSettings(thresholds={}, durations={}, activation_delays={})
NO_STATE = ConditionState(matching=frozenset(), active_since={})


def _rule(
    *,
    rule_id: str = "window.away_secure",
    in_category: Category = Category.WINDOW,
    code: str = "away_secure",
    needs: tuple[str, ...] = (),
    may_read: tuple[str, ...] = (),
    vetoes: tuple[str, ...] = (),
    delay: timedelta = timedelta(0),
    advice: Advisory | None = None,
    calls: list[Observations] | None = None,
) -> type[Rule]:
    """Build a rule class standing in for a real one."""
    seen = calls if calls is not None else []

    class _Rule:
        """A rule that returns whatever this test asked it to."""

        id = rule_id
        category = in_category
        reason_code = code
        requires = needs
        optional = may_read
        guards = vetoes
        activation_delay = delay

        def evaluate(
            self,
            obs: Observations,
            settings: RoomSettings,
            state: ConditionState,
        ) -> Advisory | None:
            """Record the call and return the prepared advice."""
            assert settings is SETTINGS
            assert state is NO_STATE
            seen.append(obs)
            return advice

    return _Rule


def _advisory(
    rule_id: str = "window.away_secure",
    category: Category = Category.WINDOW,
    action: Action = Action.CLOSE,
) -> Advisory:
    """Build an advisory attributed to a rule."""
    return Advisory(
        rule_id=rule_id,
        category=category,
        action=action,
        reason_code=rule_id.split(".")[-1],
    )


def _readable(*keys: str) -> Observations:
    """Build a snapshot in which every named key can be read."""
    return Observations({key: Observation.reading(key, 1.0) for key in keys})


def test_a_registered_rule_is_returned_for_use_as_a_decorator() -> None:
    """Registration decorates a class rather than replacing it."""
    registry = RuleRegistry()
    rule_class = _rule()
    assert registry.register(rule_class) is rule_class


def test_registration_order_is_precedence_order() -> None:
    """The order rules are declared in is the order they are considered in."""
    registry = RuleRegistry()
    for code in ("away_secure", "rain_incoming", "room_too_cold"):
        registry.register(_rule(rule_id=f"window.{code}", code=code))
    assert [rule.id for rule in registry.for_category(Category.WINDOW)] == [
        "window.away_secure",
        "window.rain_incoming",
        "window.room_too_cold",
    ]


def test_categories_are_ordered_independently() -> None:
    """A category's precedence is its own, and holds no rules of another."""
    registry = RuleRegistry()
    registry.register(_rule())
    registry.register(
        _rule(
            rule_id="fan.unoccupied_fan",
            in_category=Category.FAN,
            code="unoccupied_fan",
        )
    )
    assert [rule.id for rule in registry.for_category(Category.FAN)] == [
        "fan.unoccupied_fan"
    ]
    assert len(registry.for_category(Category.WINDOW)) == 1


def test_a_category_with_no_rules_is_empty_rather_than_missing() -> None:
    """Every category can be asked for its rules, published or not."""
    assert RuleRegistry().for_category(Category.LIGHT) == ()


def test_a_rule_can_be_looked_up_by_id() -> None:
    """Diagnostics and stabilisation reach a rule by the id advice carries."""
    registry = RuleRegistry()
    registry.register(_rule())
    assert "window.away_secure" in registry
    assert registry["window.away_secure"].reason_code == "away_secure"
    assert "window.nothing_of_the_sort" not in registry


def test_two_rules_cannot_share_an_id() -> None:
    """Identity is the rule id, so a duplicate would merge two conditions."""
    registry = RuleRegistry()
    registry.register(_rule())
    with pytest.raises(RuleDefinitionError, match="already registered"):
        registry.register(_rule())


@pytest.mark.parametrize(
    ("rule_id", "in_category", "code"),
    [
        ("window.away_secure", Category.FAN, "away_secure"),
        ("fan.away_secure", Category.WINDOW, "away_secure"),
        ("window.away_secure", Category.WINDOW, "rain_incoming"),
        ("away_secure", Category.WINDOW, "away_secure"),
    ],
)
def test_a_rule_id_must_agree_with_its_category_and_reason_code(
    rule_id: str,
    in_category: Category,
    code: str,
) -> None:
    """The id, the category and the translation key cannot drift apart."""
    with pytest.raises(RuleDefinitionError, match="must be named"):
        RuleRegistry().register(
            _rule(rule_id=rule_id, in_category=in_category, code=code)
        )


@pytest.mark.parametrize(
    ("needs", "may_read", "vetoes"),
    [
        (("rain",), ("rain",), ()),
        (("rain",), (), ("rain",)),
        ((), ("rain",), ("rain",)),
        (("rain", "rain"), (), ()),
    ],
)
def test_an_input_cannot_be_declared_two_ways(
    needs: tuple[str, ...],
    may_read: tuple[str, ...],
    vetoes: tuple[str, ...],
) -> None:
    """Each kind of input is handled differently, so an input is one kind."""
    with pytest.raises(RuleDefinitionError, match="two kinds"):
        RuleRegistry().register(_rule(needs=needs, may_read=may_read, vetoes=vetoes))


def test_a_delay_cannot_run_backwards() -> None:
    """A negative delay would publish advice before it started matching."""
    with pytest.raises(RuleDefinitionError, match="negative activation delay"):
        RuleRegistry().register(_rule(delay=timedelta(seconds=-1)))


def test_the_registry_reports_every_input_its_rules_read() -> None:
    """The vocabulary the observation layer has to supply is derived, not listed."""
    registry = RuleRegistry()
    registry.register(_rule(needs=("windows",), vetoes=("rain",)))
    registry.register(
        _rule(
            rule_id="window.passive_cooling",
            code="passive_cooling",
            needs=("windows", "indoor_temperature"),
            may_read=("outdoor_humidity",),
            vetoes=("rain",),
        )
    )
    assert registry.declared_inputs() == {
        "windows",
        "rain",
        "indoor_temperature",
        "outdoor_humidity",
    }


def test_a_key_no_room_could_supply_is_reported() -> None:
    """A mistyped key would otherwise disable a rule in every house, quietly."""
    registry = RuleRegistry()
    registry.register(_rule(needs=("windows", "indoor_temprature")))
    assert registry.undeclared_inputs({"windows", "indoor_temperature"}) == {
        "indoor_temprature"
    }


def test_a_vocabulary_that_covers_every_rule_reports_nothing() -> None:
    """Agreement between the two layers is the expected state."""
    registry = RuleRegistry()
    registry.register(_rule(needs=("windows",), vetoes=("rain",)))
    assert (
        registry.undeclared_inputs({"windows", "rain", "unused_by_any_rule"}) == set()
    )


def test_every_rule_is_reachable_across_categories() -> None:
    """Registration-time checks over the whole rule set need all of them."""
    registry = RuleRegistry()
    registry.register(_rule())
    registry.register(
        _rule(
            rule_id="light.lights_left_on",
            in_category=Category.LIGHT,
            code="lights_left_on",
        )
    )
    assert [rule.id for rule in registry.all_rules()] == [
        "window.away_secure",
        "light.lights_left_on",
    ]


def test_a_rule_runs_when_its_required_inputs_are_readable() -> None:
    """The runner is what decides a rule may look at a room."""
    calls: list[Observations] = []
    rule = _rule(needs=("windows",), advice=_advisory(), calls=calls)()
    obs = _readable("windows")

    outcome = evaluate_rule(rule, obs, SETTINGS, NO_STATE)

    assert calls == [obs]
    assert outcome.evaluated is True
    assert outcome.matched is True
    assert outcome.advisory == _advisory()
    assert outcome.unreadable_inputs == ()


def test_a_rule_that_finds_nothing_is_not_a_rule_that_could_not_look() -> None:
    """Finding nothing worth doing is not the same as being unable to look."""
    rule = _rule(needs=("windows",))()

    outcome = evaluate_rule(rule, _readable("windows"), SETTINGS, NO_STATE)

    assert outcome.evaluated is True
    assert outcome.matched is False


def test_a_rule_is_not_called_when_a_required_input_is_unreadable() -> None:
    """Rules carry no availability checks, so they must not be asked."""
    calls: list[Observations] = []
    rule = _rule(needs=("windows", "indoor_temperature"), calls=calls)()
    obs = Observations(
        {
            "windows": Observation.reading("windows", 1.0),
            "indoor_temperature": Observation.missing(
                "indoor_temperature", UnusableReason.UNAVAILABLE
            ),
        }
    )

    outcome = evaluate_rule(rule, obs, SETTINGS, NO_STATE)

    assert calls == []
    assert outcome.evaluated is False
    assert outcome.matched is False
    assert outcome.unreadable_inputs == ("indoor_temperature",)


def test_every_unreadable_input_is_reported_not_just_the_first() -> None:
    """A room awaiting three sensors should not be told about them one at a time."""
    rule = _rule(needs=("windows", "indoor_temperature", "occupancy"))()
    obs = Observations(
        {
            key: Observation.missing(key, UnusableReason.NOT_CONFIGURED)
            for key in ("windows", "indoor_temperature", "occupancy")
        }
    )

    outcome = evaluate_rule(rule, obs, SETTINGS, NO_STATE)

    assert outcome.unreadable_inputs == (
        "windows",
        "indoor_temperature",
        "occupancy",
    )


def test_an_input_the_room_never_configured_stops_the_rule() -> None:
    """A room with no CO2 sensor is a room the CO2 rule does not apply to."""
    rule = _rule(needs=("indoor_co2",))()

    outcome = evaluate_rule(rule, Observations(), SETTINGS, NO_STATE)

    assert outcome.evaluated is False
    assert outcome.unreadable_inputs == ("indoor_co2",)


def test_a_group_input_is_readable_while_one_member_answers() -> None:
    """One dead window contact does not stop every window rule."""
    calls: list[Observations] = []
    rule = _rule(needs=("windows",), calls=calls)()
    obs = Observations(
        groups={
            "windows": GroupObservation(
                key="windows",
                configured=("a", "b"),
                known_on=("a",),
                known_off=(),
                unusable=("b",),
            )
        }
    )

    assert evaluate_rule(rule, obs, SETTINGS, NO_STATE).evaluated is True
    assert calls == [obs]


def test_a_group_input_with_no_member_left_stops_the_rule() -> None:
    """Every contact dead is a room that cannot be advised about its windows."""
    rule = _rule(needs=("windows",))()
    obs = Observations(
        groups={
            "windows": GroupObservation(
                key="windows",
                configured=("a",),
                known_on=(),
                known_off=(),
                unusable=("a",),
            )
        }
    )

    assert evaluate_rule(rule, obs, SETTINGS, NO_STATE).evaluated is False


def test_optional_and_guard_inputs_do_not_gate_a_rule() -> None:
    """A guard is a veto the rule checks itself, not a reason not to run."""
    rule = _rule(may_read=("outdoor_humidity",), vetoes=("rain",))()

    assert evaluate_rule(rule, Observations(), SETTINGS, NO_STATE).evaluated is True


def test_a_rule_cannot_return_another_rule_s_advice() -> None:
    """Stabilisation timers hang off the rule id, so a copied id adopts a timer."""
    rule = _rule(advice=_advisory(rule_id="window.rain_incoming"))()

    with pytest.raises(RuleContractError, match=r"window\.rain_incoming"):
        evaluate_rule(rule, Observations(), SETTINGS, NO_STATE)


def test_a_rule_cannot_return_advice_for_another_category() -> None:
    """Advice is published per category, so a stray one would land elsewhere."""
    rule = _rule(
        rule_id="fan.unoccupied_fan",
        in_category=Category.FAN,
        code="unoccupied_fan",
        advice=_advisory(
            rule_id="fan.unoccupied_fan",
            category=Category.WINDOW,
            action=Action.CLOSE,
        ),
    )()

    with pytest.raises(RuleContractError, match="window"):
        evaluate_rule(rule, Observations(), SETTINGS, NO_STATE)


def test_a_rule_cannot_return_another_rule_s_reason() -> None:
    """A copied reason code publishes the right advice with the wrong wording."""
    rule = _rule(
        advice=Advisory(
            rule_id="window.away_secure",
            category=Category.WINDOW,
            action=Action.CLOSE,
            reason_code="rain_incoming",
        )
    )()

    with pytest.raises(RuleContractError, match="rain_incoming"):
        evaluate_rule(rule, Observations(), SETTINGS, NO_STATE)


def test_a_rule_that_raises_is_not_hidden() -> None:
    """Reporting a bug as "no advice" hides it behind a condition that may hold."""

    class _Broken:
        """A rule with a defect in it."""

        id = "window.away_secure"
        category = Category.WINDOW
        reason_code = "away_secure"
        requires = ()
        optional = ()
        guards = ()
        activation_delay = timedelta(0)

        def evaluate(
            self,
            obs: Observations,
            settings: RoomSettings,
            state: ConditionState,
        ) -> Advisory | None:
            """Fail the way a real defect would."""
            raise ZeroDivisionError(
                len(obs) + len(settings.durations) + len(state.matching)
            )

    with pytest.raises(ZeroDivisionError):
        evaluate_rule(_Broken(), Observations(), SETTINGS, NO_STATE)


def test_every_rule_is_offered_the_room_even_below_a_match() -> None:
    """A lower-ranked rule must be known to be matching while a delay runs."""
    higher = _rule(advice=_advisory())()
    lower = _rule(
        rule_id="window.rain_incoming",
        code="rain_incoming",
        advice=_advisory(rule_id="window.rain_incoming"),
    )()

    outcomes = evaluate_all([higher, lower], Observations(), SETTINGS, NO_STATE)

    assert [outcome.rule_id for outcome in outcomes] == [
        "window.away_secure",
        "window.rain_incoming",
    ]
    assert all(outcome.matched for outcome in outcomes)


def test_running_no_rules_is_not_an_error() -> None:
    """A category a room did not enable simply has nothing to report."""
    assert evaluate_all([], Observations(), SETTINGS, NO_STATE) == ()


def test_outcomes_line_up_with_the_rules_that_produced_them() -> None:
    """A rule that could not run still gets an outcome, in its own place."""
    ready = _rule(needs=("windows",), advice=_advisory())()
    waiting = _rule(
        rule_id="window.room_too_cold",
        code="room_too_cold",
        needs=("indoor_temperature",),
    )()

    outcomes = evaluate_all([ready, waiting], _readable("windows"), SETTINGS, NO_STATE)

    assert [outcome.rule_id for outcome in outcomes] == [
        "window.away_secure",
        "window.room_too_cold",
    ]
    assert [outcome.evaluated for outcome in outcomes] == [True, False]
    assert outcomes[1].unreadable_inputs == ("indoor_temperature",)


def test_the_registry_reports_the_keys_that_must_always_be_present() -> None:
    """Guards are read ungated, so a room missing one raises rather than skips."""
    registry = RuleRegistry()
    registry.register(_rule(needs=("windows",), vetoes=("rain",)))
    registry.register(
        _rule(
            rule_id="window.passive_cooling",
            code="passive_cooling",
            needs=("windows",),
            vetoes=("rain", "outdoor_air_quality"),
        )
    )
    assert registry.guard_inputs() == {"rain", "outdoor_air_quality"}


def test_a_recorded_read_outside_the_declared_inputs_is_caught() -> None:
    """The wrapper every rule is tested against notices an undeclared read."""
    obs = RecordingObservations(
        {
            "windows": Observation.reading("windows", 1.0),
            "indoor_temperature": Observation.reading("indoor_temperature", 70.0),
        }
    )
    rule = _rule(needs=("windows",))()

    obs.value("windows")
    obs.value("indoor_temperature")

    assert obs.undeclared_reads(rule) == {"indoor_temperature"}


def test_a_rule_reading_only_what_it_declared_records_nothing_undeclared() -> None:
    """The wrapper is silent about the reads a rule is entitled to make."""
    obs = RecordingObservations(
        {
            "windows": Observation.reading("windows", 1.0),
            "outdoor_humidity": Observation.reading("outdoor_humidity", 40.0),
            "rain": Observation.missing("rain", UnusableReason.NOT_CONFIGURED),
        }
    )
    rule = _rule(needs=("windows",), may_read=("outdoor_humidity",), vetoes=("rain",))()

    obs.usable("windows")
    obs["windows"]
    obs.get_value("outdoor_humidity")
    obs.guard("rain")

    assert obs.undeclared_reads(rule) == frozenset()


def test_reading_a_group_is_recorded() -> None:
    """Groups are reached through their own accessor and are recorded too."""
    obs = _with_windows()
    rule = _rule()()

    obs.group("windows")

    assert obs.undeclared_reads(rule) == {"windows"}


def test_reading_a_group_through_the_mapping_is_recorded() -> None:
    """The groups mapping is a second way in, so it records as well."""
    obs = _with_windows()
    rule = _rule()()

    assert obs.groups["windows"].any_known_on is True

    assert obs.undeclared_reads(rule) == {"windows"}


def test_asking_whether_a_group_exists_is_recorded() -> None:
    """Branching on a group's presence is a read of it, and is declared like one."""
    obs = _with_windows()
    rule = _rule()()

    assert "windows" in obs.groups

    assert obs.undeclared_reads(rule) == {"windows"}


def test_listing_the_groups_leaves_them_unread() -> None:
    """Diagnostics may walk the snapshot without that counting against a rule."""
    obs = _with_windows()
    rule = _rule()()

    assert list(obs.groups) == ["windows"]
    assert len(obs.groups) == 1

    assert obs.undeclared_reads(rule) == frozenset()


def _with_windows() -> RecordingObservations:
    """Build a recording snapshot holding one group of window contacts."""
    return RecordingObservations(
        groups={
            "windows": GroupObservation(
                key="windows",
                configured=("a",),
                known_on=("a",),
                known_off=(),
                unusable=(),
            )
        }
    )

"""Tests for observations computed from other observations."""

from __future__ import annotations

import pytest

from custom_components.room_advisor.models import (
    GroupObservation,
    GuardState,
    Observation,
    Observations,
    UnusableReason,
)
from custom_components.room_advisor.observations import (
    DERIVED_KEYS,
    OBSERVATION_KEYS,
    derive_observations,
)

_CELSIUS = "°C"
_FAHRENHEIT = "°F"


def _reading(key: str, value: float, unit: str | None = _CELSIUS) -> Observation:
    """Build a usable source reading."""
    return Observation.reading(key, value, unit=unit, source_entity_id=f"sensor.{key}")


def _missing(key: str, reason: UnusableReason) -> Observation:
    """Build an unusable source reading."""
    return Observation.missing(key, reason, source_entity_id=f"sensor.{key}")


def _snapshot(**sources: Observation) -> Observations:
    """Build a snapshot holding only the named sources."""
    return Observations(sources)


def _derived(margin: float = 0.0, **sources: Observation) -> Observations:
    """Derive from a snapshot holding only the named sources."""
    return derive_observations(_snapshot(**sources), uncertainty_margin=margin)


# Vocabulary


def test_the_derived_keys_are_what_they_are() -> None:
    """Rules name these keys, and a renamed one silently stops a rule running."""
    assert sorted(DERIVED_KEYS) == ["outdoor_dew_point", "temperature_advantage"]


def test_the_observation_keys_are_every_key_a_rule_may_name() -> None:
    """The runner checks a rule's declared inputs against this set.

    Stated literally, because a key missing from it disables the rule that
    names it rather than failing.
    """
    assert sorted(OBSERVATION_KEYS) == [
        "away",
        "fan",
        "hvac_conditioning",
        "indoor_co2",
        "indoor_temperature",
        "lights",
        "occupancy",
        "outdoor_air_quality",
        "outdoor_dew_point",
        "outdoor_humidity",
        "outdoor_temperature",
        "rain_risk",
        "temperature_advantage",
        "window_contacts",
    ]


def test_every_derived_key_is_present_even_with_no_sources_at_all() -> None:
    """A key the snapshot omits raises when a rule reaches for it.

    A source the snapshot never carried reads as unconfigured, so a derivation
    always produces an observation rather than depending on what it was given.
    """
    observations = derive_observations(Observations())

    assert set(observations) >= DERIVED_KEYS
    assert all(
        observations[key].unusable_reason is UnusableReason.NOT_CONFIGURED
        for key in DERIVED_KEYS
    )
    assert all(
        observations.guard(key) is GuardState.NOT_CONFIGURED for key in DERIVED_KEYS
    )


def test_deriving_keeps_the_readings_it_was_given() -> None:
    """The snapshot is added to, not replaced."""
    observations = derive_observations(
        Observations(
            {"indoor_temperature": _reading("indoor_temperature", 21.0)},
            {"lights": GroupObservation("lights", ("light.a",), ("light.a",), (), ())},
        )
    )

    assert observations.value("indoor_temperature") == 21.0
    assert observations.groups["lights"].any_known_on


# Dew point


@pytest.mark.parametrize(
    ("temperature", "humidity", "expected"),
    [
        (20.0, 50.0, 9.255175),
        (25.0, 60.0, 16.693149),
        (0.0, 80.0, -3.040421),
        (-10.0, 90.0, -11.329007),
    ],
    ids=["mild", "warm and humid", "freezing", "below freezing"],
)
def test_the_dew_point_follows_the_magnus_approximation(
    temperature: float, humidity: float, expected: float
) -> None:
    """The coefficients are Home Assistant's own, so the two agree on a house."""
    observations = _derived(
        outdoor_temperature=_reading("outdoor_temperature", temperature),
        outdoor_humidity=_reading("outdoor_humidity", humidity, "%"),
    )

    assert observations.value("outdoor_dew_point") == pytest.approx(expected)


def test_saturated_air_has_a_dew_point_equal_to_its_temperature() -> None:
    """The one point on the curve that needs no coefficients to check."""
    observations = _derived(
        outdoor_temperature=_reading("outdoor_temperature", 30.0),
        outdoor_humidity=_reading("outdoor_humidity", 100.0, "%"),
    )

    assert observations.value("outdoor_dew_point") == pytest.approx(30.0)


def test_the_dew_point_is_reported_in_the_unit_it_was_read_in() -> None:
    """The ceiling it is compared against is configured in the same unit."""
    observations = _derived(
        outdoor_temperature=_reading("outdoor_temperature", 68.0, _FAHRENHEIT),
        outdoor_humidity=_reading("outdoor_humidity", 50.0, "%"),
    )

    assert observations.value("outdoor_dew_point") == pytest.approx(48.659314)
    assert observations["outdoor_dew_point"].unit == _FAHRENHEIT


@pytest.mark.parametrize(
    "humidity",
    [0.0, -5.0, 100.1, 1000.0],
    ids=["zero", "negative", "just over full", "wildly over full"],
)
def test_a_humidity_off_the_scale_has_no_dew_point(humidity: float) -> None:
    """Refused rather than answered: the formula returns a number regardless."""
    observations = _derived(
        outdoor_temperature=_reading("outdoor_temperature", 20.0),
        outdoor_humidity=_reading("outdoor_humidity", humidity, "%"),
    )

    assert (
        observations["outdoor_dew_point"].unusable_reason
        is UnusableReason.UNCONVERTIBLE
    )


@pytest.mark.parametrize(
    ("temperature", "humidity"),
    [(-243.12, 50.0), (1e19, 100.0)],
    ids=["the denominator's pole", "the coefficient cancelling"],
)
def test_a_reading_at_a_pole_of_the_formula_has_no_dew_point(
    temperature: float, humidity: float
) -> None:
    """Python raises on a float division by zero rather than returning infinity.

    An uncaught one would lose the whole snapshot, not just this observation.
    """
    observations = _derived(
        outdoor_temperature=_reading("outdoor_temperature", temperature),
        outdoor_humidity=_reading("outdoor_humidity", humidity, "%"),
    )

    assert (
        observations["outdoor_dew_point"].unusable_reason
        is UnusableReason.UNCONVERTIBLE
    )


@pytest.mark.parametrize(
    "unit", [None, "ppm", "g/m³"], ids=["no unit named", "not humidity", "absolute"]
)
def test_a_humidity_not_in_percent_has_no_dew_point(unit: str | None) -> None:
    """A fraction of 0.63 is inside every bound a percentage has.

    Read as a percentage it puts the dew point 55°C too low, which is the
    direction that advises opening a window onto muggy air.
    """
    observations = _derived(
        outdoor_temperature=_reading("outdoor_temperature", 20.0),
        outdoor_humidity=_reading("outdoor_humidity", 0.63, unit),
    )

    assert (
        observations["outdoor_dew_point"].unusable_reason
        is UnusableReason.UNCONVERTIBLE
    )


@pytest.mark.parametrize(
    "unit", [None, "lumens"], ids=["no unit named", "not a temperature"]
)
def test_a_temperature_in_no_known_scale_has_no_dew_point(unit: str | None) -> None:
    """Converting to Celsius is the first step, and it has to be possible."""
    observations = _derived(
        outdoor_temperature=_reading("outdoor_temperature", 20.0, unit),
        outdoor_humidity=_reading("outdoor_humidity", 50.0, "%"),
    )

    assert (
        observations["outdoor_dew_point"].unusable_reason
        is UnusableReason.UNCONVERTIBLE
    )


# Temperature advantage


def test_the_temperature_advantage_is_how_much_cooler_it_is_outside() -> None:
    """Positive means opening the window would cool the room."""
    observations = _derived(
        indoor_temperature=_reading("indoor_temperature", 26.0),
        outdoor_temperature=_reading("outdoor_temperature", 20.0),
    )

    assert observations.value("temperature_advantage") == pytest.approx(6.0)
    assert observations["temperature_advantage"].unit == _CELSIUS


def test_a_warmer_outside_is_a_negative_advantage() -> None:
    """No rule may read a disadvantage as a small advantage."""
    observations = _derived(
        indoor_temperature=_reading("indoor_temperature", 20.0),
        outdoor_temperature=_reading("outdoor_temperature", 26.0),
    )

    assert observations.value("temperature_advantage") == pytest.approx(-6.0)


def test_the_uncertainty_margin_is_taken_off_the_advantage() -> None:
    """A regional forecast is discounted before any rule compares it."""
    observations = _derived(
        margin=1.1,
        indoor_temperature=_reading("indoor_temperature", 26.0),
        outdoor_temperature=_reading("outdoor_temperature", 20.0),
    )

    assert observations.value("temperature_advantage") == pytest.approx(4.9)


def test_the_margin_only_ever_reduces_the_advantage() -> None:
    """It exists to make advice more cautious, never less."""
    without = _derived(
        indoor_temperature=_reading("indoor_temperature", 26.0),
        outdoor_temperature=_reading("outdoor_temperature", 20.0),
    ).value("temperature_advantage")
    with_margin = _derived(
        margin=2.0,
        indoor_temperature=_reading("indoor_temperature", 26.0),
        outdoor_temperature=_reading("outdoor_temperature", 20.0),
    ).value("temperature_advantage")

    assert with_margin < without


def test_an_advantage_that_is_not_a_finite_number_is_unusable() -> None:
    """Infinity compares against a threshold without complaint."""
    observations = _derived(
        indoor_temperature=_reading("indoor_temperature", float("inf")),
        outdoor_temperature=_reading("outdoor_temperature", 20.0),
    )

    assert (
        observations["temperature_advantage"].unusable_reason
        is UnusableReason.UNCONVERTIBLE
    )


# Inheriting a reason


def test_a_derivation_is_unconfigured_only_when_every_source_is() -> None:
    """Degraded mode is for a sensor the user never bought."""
    observations = _derived(
        outdoor_temperature=_missing(
            "outdoor_temperature", UnusableReason.NOT_CONFIGURED
        ),
        outdoor_humidity=_missing("outdoor_humidity", UnusableReason.NOT_CONFIGURED),
    )

    assert (
        observations["outdoor_dew_point"].unusable_reason
        is UnusableReason.NOT_CONFIGURED
    )
    assert observations.guard("outdoor_dew_point") is GuardState.NOT_CONFIGURED


@pytest.mark.parametrize(
    ("temperature", "humidity", "expected"),
    [
        (
            UnusableReason.NOT_CONFIGURED,
            UnusableReason.UNAVAILABLE,
            UnusableReason.UNAVAILABLE,
        ),
        (
            UnusableReason.UNAVAILABLE,
            UnusableReason.NOT_CONFIGURED,
            UnusableReason.UNAVAILABLE,
        ),
        (
            UnusableReason.NOT_CONFIGURED,
            UnusableReason.UNKNOWN,
            UnusableReason.UNKNOWN,
        ),
        (
            UnusableReason.NOT_CONFIGURED,
            UnusableReason.NOT_YET_SEEN,
            UnusableReason.NOT_YET_SEEN,
        ),
    ],
    ids=["dead second", "dead first", "unknown", "not yet seen"],
)
def test_any_real_failure_outranks_an_unconfigured_source(
    temperature: UnusableReason,
    humidity: UnusableReason,
    expected: UnusableReason,
) -> None:
    """One unconfigured source and one dead source is a broken sensor.

    Reading it as unconfigured would run the rule in degraded mode, which is
    exactly the case degraded mode must not cover.
    """
    observations = _derived(
        outdoor_temperature=_missing("outdoor_temperature", temperature),
        outdoor_humidity=_missing("outdoor_humidity", humidity),
    )

    assert observations["outdoor_dew_point"].unusable_reason is expected
    assert observations.guard("outdoor_dew_point") is GuardState.UNUSABLE


def test_a_dead_source_withholds_where_an_absent_one_would_not() -> None:
    """The two cases differ by one field, and opposite advice follows."""
    absent = _derived(
        outdoor_temperature=_reading("outdoor_temperature", 20.0),
        outdoor_humidity=_missing("outdoor_humidity", UnusableReason.NOT_CONFIGURED),
    )
    dead = _derived(
        outdoor_temperature=_reading("outdoor_temperature", 20.0),
        outdoor_humidity=_missing("outdoor_humidity", UnusableReason.UNAVAILABLE),
    )

    assert absent.guard("outdoor_dew_point") is GuardState.NOT_CONFIGURED
    assert dead.guard("outdoor_dew_point") is GuardState.UNUSABLE


def test_the_first_failing_source_in_order_is_the_one_reported() -> None:
    """Two real failures resolve the same way; only the named entity differs."""
    observations = _derived(
        outdoor_temperature=_missing("outdoor_temperature", UnusableReason.UNKNOWN),
        outdoor_humidity=_missing("outdoor_humidity", UnusableReason.UNAVAILABLE),
    )

    assert observations["outdoor_dew_point"].unusable_reason is UnusableReason.UNKNOWN
    assert (
        observations["outdoor_dew_point"].source_entity_id
        == "sensor.outdoor_temperature"
    )


def test_an_inherited_failure_names_the_source_that_caused_it() -> None:
    """A room reporting an unusable input has to say which entity."""
    observations = _derived(
        outdoor_temperature=_reading("outdoor_temperature", 20.0),
        outdoor_humidity=_missing("outdoor_humidity", UnusableReason.UNAVAILABLE),
    )

    assert (
        observations["outdoor_dew_point"].source_entity_id == "sensor.outdoor_humidity"
    )


def test_a_derivation_never_carries_a_value_it_could_not_compute() -> None:
    """A guard reading `None` would find it falsy and report satisfied."""
    observations = _derived(
        indoor_temperature=_reading("indoor_temperature", 26.0),
        outdoor_temperature=_missing("outdoor_temperature", UnusableReason.UNAVAILABLE),
    )

    assert observations["temperature_advantage"].value is None
    assert not observations["temperature_advantage"].usable

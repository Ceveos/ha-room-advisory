"""Tests for reading Home Assistant's states into a room's observations."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_system import METRIC_SYSTEM, US_CUSTOMARY_SYSTEM

from custom_components.room_advisor.models import (
    GuardState,
    Observations,
    UnusableReason,
)
from custom_components.room_advisor.observations import (
    BUILT_KEYS,
    build_observations,
)


def _set(
    hass: HomeAssistant,
    entity_id: str,
    state: str,
    attributes: dict[str, Any] | None = None,
) -> None:
    """Publish one entity state."""
    hass.states.async_set(entity_id, state, attributes or {})


def _build(
    hass: HomeAssistant,
    *,
    shared: dict[str, Any] | None = None,
    room: dict[str, Any] | None = None,
) -> Observations:
    """Read a house with these inputs stored."""
    return build_observations(hass, shared or {}, room or {})


def test_every_key_is_built_for_a_room_that_has_nothing(hass: HomeAssistant) -> None:
    """A guard is skipped only because it says it was never configured.

    A key the snapshot omits raises when a rule reaches for it, so an empty
    room has to carry the whole vocabulary.
    """
    observations = _build(hass)

    assert set(observations) | set(observations.groups) == BUILT_KEYS
    assert all(
        observations[key].unusable_reason is UnusableReason.NOT_CONFIGURED
        for key in observations
    )
    assert not any(observations.groups[key].usable for key in observations.groups)


def test_every_built_key_can_be_read_as_a_guard(hass: HomeAssistant) -> None:
    """The runner validates a rule's guards against the vocabulary and nothing more.

    A key in the vocabulary that raises when guarded on passes validation and
    then fails in every room, so membership has to imply guardability.
    """
    observations = _build(hass)

    assert all(
        observations.guard(key) is GuardState.NOT_CONFIGURED for key in BUILT_KEYS
    )


def test_the_built_keys_are_what_they_are() -> None:
    """Rules name these keys, and the runner checks its vocabulary against them.

    Stated literally: a renamed key does not fail, it quietly stops a rule
    from ever running.
    """
    assert sorted(BUILT_KEYS) == [
        "away",
        "fan",
        "hvac_conditioning",
        "indoor_co2",
        "indoor_temperature",
        "lights",
        "occupancy",
        "outdoor_air_quality",
        "outdoor_humidity",
        "outdoor_temperature",
        "rain_risk",
        "window_contacts",
    ]


def test_an_unconfigured_guard_is_not_configured(hass: HomeAssistant) -> None:
    """The distinction the whole guard model turns on."""
    observations = _build(hass)

    assert observations.guard("rain_risk") is GuardState.NOT_CONFIGURED
    assert observations.guard("outdoor_air_quality") is GuardState.NOT_CONFIGURED


def test_a_configured_guard_that_cannot_be_read_is_unusable(
    hass: HomeAssistant,
) -> None:
    """A broken rain sensor is not 'no rain'."""
    _set(hass, "binary_sensor.rain", "unavailable")

    observations = _build(hass, shared={"rain_risk": "binary_sensor.rain"})

    assert observations.guard("rain_risk") is GuardState.UNUSABLE


def test_a_room_reads_its_own_inputs_and_the_house_reads_its_own(
    hass: HomeAssistant,
) -> None:
    """The two stores hold different keys under the same name.

    Reading a room's entities out of the house's inputs, or the reverse, would
    silently produce a room that observes nothing.
    """
    _set(hass, "sensor.outside", "4", {"unit_of_measurement": "°C"})
    _set(hass, "sensor.desk", "21", {"unit_of_measurement": "°C"})

    misfiled = _build(
        hass,
        shared={"indoor_temperature": "sensor.desk"},
        room={"outdoor_temperature": "sensor.outside"},
    )

    assert not misfiled.usable("indoor_temperature")
    assert not misfiled.usable("outdoor_temperature")


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        pytest.param("unavailable", UnusableReason.UNAVAILABLE, id="unavailable"),
        pytest.param("unknown", UnusableReason.UNKNOWN, id="unknown"),
        pytest.param("warm", UnusableReason.UNCONVERTIBLE, id="not a number"),
        pytest.param("nan", UnusableReason.UNCONVERTIBLE, id="nan"),
        pytest.param("inf", UnusableReason.UNCONVERTIBLE, id="infinity"),
        pytest.param("-inf", UnusableReason.UNCONVERTIBLE, id="negative infinity"),
    ],
)
def test_a_reading_that_is_not_a_reading(
    hass: HomeAssistant, state: str, reason: UnusableReason
) -> None:
    """`nan` and `inf` survive arithmetic and comparison silently.

    A rule handed one would compare it against a threshold, get an answer, and
    publish advice derived from a broken sensor.
    """
    _set(hass, "sensor.desk", state, {"unit_of_measurement": "°C"})

    observation = _build(hass, room={"indoor_temperature": "sensor.desk"})[
        "indoor_temperature"
    ]

    assert observation.unusable_reason is reason
    assert observation.source_entity_id == "sensor.desk"


def test_an_entity_that_has_not_reported_yet(hass: HomeAssistant) -> None:
    """Startup has no blackout, so a silent input is simply not readable yet."""
    observation = _build(hass, room={"indoor_temperature": "sensor.desk"})[
        "indoor_temperature"
    ]

    assert observation.unusable_reason is UnusableReason.NOT_YET_SEEN


def test_a_temperature_is_converted_to_the_unit_system(hass: HomeAssistant) -> None:
    """Rules and thresholds work in one unit system and never convert."""
    hass.config.units = METRIC_SYSTEM
    _set(hass, "sensor.desk", "72", {"unit_of_measurement": "°F"})

    observation = _build(hass, room={"indoor_temperature": "sensor.desk"})[
        "indoor_temperature"
    ]

    assert observation.value == pytest.approx(22.222, abs=0.001)
    assert observation.unit == "°C"


def test_a_temperature_already_in_the_unit_system_is_left_alone(
    hass: HomeAssistant,
) -> None:
    """Converting a value to the unit it is already in must not disturb it."""
    hass.config.units = US_CUSTOMARY_SYSTEM
    _set(hass, "sensor.desk", "70.5", {"unit_of_measurement": "°F"})

    observation = _build(hass, room={"indoor_temperature": "sensor.desk"})[
        "indoor_temperature"
    ]

    assert observation.value == 70.5
    assert observation.unit == "°F"


@pytest.mark.parametrize(
    "attributes",
    [
        pytest.param({}, id="no unit at all"),
        pytest.param({"unit_of_measurement": "ppm"}, id="not a temperature"),
    ],
)
def test_a_temperature_that_cannot_be_placed_in_a_scale(
    hass: HomeAssistant, attributes: dict[str, Any]
) -> None:
    """A source naming no unit is refused rather than assumed.

    A Fahrenheit reading taken for Celsius is wrong by enough to advise
    opening a window in a blizzard.
    """
    hass.config.units = METRIC_SYSTEM
    _set(hass, "sensor.desk", "70", attributes)

    observation = _build(hass, room={"indoor_temperature": "sensor.desk"})[
        "indoor_temperature"
    ]

    assert observation.unusable_reason is UnusableReason.UNCONVERTIBLE


def test_a_plain_number_keeps_the_unit_it_reports(hass: HomeAssistant) -> None:
    """Only temperature is normalised; nothing else has two scales in use."""
    _set(hass, "sensor.co2", "820", {"unit_of_measurement": "ppm"})
    _set(hass, "sensor.outside_humidity", "63", {"unit_of_measurement": "%"})

    observations = _build(
        hass,
        shared={"outdoor_humidity": "sensor.outside_humidity"},
        room={"indoor_co2": "sensor.co2"},
    )

    assert observations.value("indoor_co2") == 820
    assert observations["indoor_co2"].unit == "ppm"
    assert observations.value("outdoor_humidity") == 63
    assert observations["outdoor_humidity"].unit == "%"


def test_a_weather_entity_is_read_from_its_attributes(hass: HomeAssistant) -> None:
    """A weather entity's state is its condition, not a number.

    Its forecast is never read: rain risk is an input the user supplies.
    """
    hass.config.units = METRIC_SYSTEM
    _set(
        hass,
        "weather.home",
        "rainy",
        {"temperature": 50.0, "temperature_unit": "°F", "humidity": 88},
    )

    observations = _build(
        hass,
        shared={
            "outdoor_temperature": "weather.home",
            "outdoor_humidity": "weather.home",
        },
    )

    assert observations.value("outdoor_temperature") == pytest.approx(10.0)
    assert observations["outdoor_temperature"].unit == "°C"
    assert observations.value("outdoor_humidity") == 88
    assert observations["outdoor_humidity"].unit == "%"


def test_a_weather_entity_that_reports_no_temperature(hass: HomeAssistant) -> None:
    """A weather integration may publish a condition and nothing else."""
    _set(hass, "weather.home", "sunny", {"humidity": 40})

    observation = _build(hass, shared={"outdoor_temperature": "weather.home"})[
        "outdoor_temperature"
    ]

    assert observation.unusable_reason is UnusableReason.UNKNOWN


@pytest.mark.parametrize(
    ("entity_id", "state", "expected"),
    [
        pytest.param("binary_sensor.motion", "on", True, id="binary sensor on"),
        pytest.param("binary_sensor.motion", "off", False, id="binary sensor off"),
        pytest.param("input_boolean.guest", "on", True, id="helper on"),
        pytest.param("person.alex", "home", True, id="person at home"),
        pytest.param("person.alex", "Office", True, id="person in a zone"),
        pytest.param("person.alex", "not_home", False, id="person away"),
    ],
)
def test_occupancy_is_read_from_whatever_says_someone_is_here(
    hass: HomeAssistant, entity_id: str, state: str, *, expected: bool
) -> None:
    """A tracker reports the zone it is in, so anything but `not_home` is here."""
    _set(hass, entity_id, state)

    assert _build(hass, room={"occupancy": entity_id}).value("occupancy") is expected


def test_a_state_that_is_neither_on_nor_off(hass: HomeAssistant) -> None:
    """An on/off input that reports something else is not half on."""
    _set(hass, "binary_sensor.motion", "open")

    observation = _build(hass, room={"occupancy": "binary_sensor.motion"})["occupancy"]

    assert observation.unusable_reason is UnusableReason.UNCONVERTIBLE


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        pytest.param("armed_away", True, id="armed away"),
        pytest.param("armed_vacation", True, id="armed for a holiday"),
        pytest.param("armed_home", False, id="armed with people in"),
        pytest.param("armed_night", False, id="armed overnight"),
        pytest.param("armed_custom_bypass", False, id="armed with a bypass"),
        pytest.param("disarmed", False, id="disarmed"),
        pytest.param("arming", False, id="arming"),
        pytest.param("pending", False, id="pending"),
        pytest.param("triggered", False, id="triggered"),
    ],
)
def test_an_alarm_panel_says_the_house_is_empty_only_when_armed_for_an_absence(
    hass: HomeAssistant, state: str, *, expected: bool
) -> None:
    """`triggered` is deliberately not away: window advice during an alarm is noise."""
    _set(hass, "alarm_control_panel.home", state)

    observations = _build(hass, shared={"away": ["alarm_control_panel.home"]})

    assert observations.value("away") is expected
    assert observations["away"].source_entity_id == "alarm_control_panel.home"


def test_an_alarm_panel_reporting_something_unrecognised(hass: HomeAssistant) -> None:
    """Reading an unknown armed state as 'at home' would withhold safety advice."""
    _set(hass, "alarm_control_panel.home", "armed_moon_base")

    observation = _build(hass, shared={"away": ["alarm_control_panel.home"]})["away"]

    assert observation.unusable_reason is UnusableReason.UNCONVERTIBLE


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        pytest.param("not_home", "not_home", True, id="everyone out"),
        pytest.param("not_home", "home", False, id="one still in"),
        pytest.param("Office", "not_home", False, id="one in a zone"),
    ],
)
def test_the_house_is_empty_only_when_every_tracker_is_out(
    hass: HomeAssistant, first: str, second: str, *, expected: bool
) -> None:
    """One person at home makes the house occupied, whatever the others do."""
    _set(hass, "person.alex", first)
    _set(hass, "device_tracker.phone", second)

    observations = _build(
        hass, shared={"away": ["person.alex", "device_tracker.phone"]}
    )

    assert observations.value("away") is expected
    assert observations["away"].source_entity_id is None


def test_one_unreadable_tracker_makes_the_house_unreadable(
    hass: HomeAssistant,
) -> None:
    """Half an answer about whether the house is empty is worse than none.

    The member that failed is named, because that is the one to go and fix.
    """
    _set(hass, "person.alex", "not_home")
    _set(hass, "device_tracker.phone", "unavailable")

    observation = _build(
        hass, shared={"away": ["person.alex", "device_tracker.phone"]}
    )["away"]

    assert observation.unusable_reason is UnusableReason.UNAVAILABLE
    assert observation.source_entity_id == "device_tracker.phone"


def test_a_toggle_can_stand_in_for_the_alarm(hass: HomeAssistant) -> None:
    """Not every house has a panel; on means away."""
    _set(hass, "input_boolean.holiday", "on")

    assert _build(hass, shared={"away": ["input_boolean.holiday"]}).value("away")


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        pytest.param("heating", True, id="heating"),
        pytest.param("cooling", True, id="cooling"),
        pytest.param("idle", False, id="idle"),
        pytest.param("off", False, id="off"),
        pytest.param("fan", False, id="fan only"),
        pytest.param("drying", False, id="drying"),
        pytest.param("preheating", False, id="preheating"),
        pytest.param("defrosting", False, id="defrosting"),
    ],
)
def test_a_thermostat_is_conditioning_only_while_it_is_working(
    hass: HomeAssistant, action: str, *, expected: bool
) -> None:
    """A thermostat in heat mode that has reached its setpoint is idle."""
    _set(hass, "climate.office", "heat", {"hvac_action": action})

    observations = _build(hass, room={"hvac": "climate.office"})

    assert observations.value("hvac_conditioning") is expected


@pytest.mark.parametrize(
    "attributes",
    [
        pytest.param({}, id="no action published"),
        pytest.param({"hvac_action": "sulking"}, id="an action we do not know"),
    ],
)
def test_a_thermostat_that_does_not_say_what_it_is_doing(
    hass: HomeAssistant, attributes: dict[str, Any]
) -> None:
    """`hvac_action` is optional in Home Assistant's climate API.

    Falling back to the mode would advise closing a window because the heating
    is on when it is not.
    """
    _set(hass, "climate.office", "heat", attributes)

    observation = _build(hass, room={"hvac": "climate.office"})["hvac_conditioning"]

    assert observation.unusable_reason is UnusableReason.UNCONVERTIBLE


def test_a_group_keeps_which_member_is_which(hass: HomeAssistant) -> None:
    """Reducing a group to a boolean loses what partial availability needs."""
    _set(hass, "binary_sensor.left", "on")
    _set(hass, "binary_sensor.right", "off")
    _set(hass, "binary_sensor.rear", "unavailable")

    group = _build(
        hass,
        room={
            "window_contacts": [
                "binary_sensor.left",
                "binary_sensor.right",
                "binary_sensor.rear",
            ]
        },
    ).groups["window_contacts"]

    assert group.configured == (
        "binary_sensor.left",
        "binary_sensor.right",
        "binary_sensor.rear",
    )
    assert group.known_on == ("binary_sensor.left",)
    assert group.known_off == ("binary_sensor.right",)
    assert group.unusable == ("binary_sensor.rear",)


def test_one_dead_contact_permits_closing_and_withholds_opening(
    hass: HomeAssistant,
) -> None:
    """Advice to close is permitted on partial information; advice to open is not."""
    _set(hass, "binary_sensor.left", "on")
    _set(hass, "binary_sensor.rear", "unavailable")

    group = _build(
        hass, room={"window_contacts": ["binary_sensor.left", "binary_sensor.rear"]}
    ).groups["window_contacts"]

    assert group.usable
    assert group.any_known_on
    assert not group.all_usable_and_off


def test_a_group_whose_every_member_is_dead_is_unusable(hass: HomeAssistant) -> None:
    """No readable member means every rule that needs the group is skipped."""
    _set(hass, "light.desk", "unavailable")

    group = _build(hass, room={"lights": ["light.desk"]}).groups["lights"]

    assert group.configured == ("light.desk",)
    assert not group.usable


def test_a_repeated_reading_is_not_read_twice(hass: HomeAssistant) -> None:
    """One entity may serve two inputs without either disturbing the other."""
    _set(hass, "binary_sensor.motion", "on")

    observations = _build(
        hass,
        room={"occupancy": "binary_sensor.motion", "fan": "binary_sensor.motion"},
    )

    assert observations.value("occupancy") is True
    assert observations.value("fan") is True


def test_an_entity_stored_twice_in_a_group_is_read_once(hass: HomeAssistant) -> None:
    """A group's members must partition it, so a repeat would raise on build.

    Stored data is not re-cleaned on read, and one raise loses the whole room.
    """
    _set(hass, "binary_sensor.left", "on")

    group = _build(
        hass, room={"window_contacts": ["binary_sensor.left", "binary_sensor.left"]}
    ).groups["window_contacts"]

    assert group.configured == ("binary_sensor.left",)
    assert group.known_on == ("binary_sensor.left",)


def test_a_single_entity_input_reads_the_first_of_several_stored(
    hass: HomeAssistant,
) -> None:
    """Over-specified stored data reads one entity rather than raising."""
    _set(hass, "sensor.first", "18", {"unit_of_measurement": "°C"})
    _set(hass, "sensor.second", "24", {"unit_of_measurement": "°C"})

    observation = _build(
        hass, room={"indoor_temperature": ["sensor.first", "sensor.second"]}
    )["indoor_temperature"]

    assert observation.value == 18
    assert observation.source_entity_id == "sensor.first"


@pytest.mark.parametrize(
    "unit", [None, "ppm"], ids=["no unit named", "not a percentage"]
)
def test_a_hygrometer_that_does_not_report_percent_is_unusable(
    hass: HomeAssistant, unit: str | None
) -> None:
    """A fraction of 0.63 is inside every bound a percentage has."""
    _set(hass, "sensor.rh", "0.63", {"unit_of_measurement": unit} if unit else {})

    observation = _build(hass, shared={"outdoor_humidity": "sensor.rh"})[
        "outdoor_humidity"
    ]

    assert observation.unusable_reason is UnusableReason.UNCONVERTIBLE


@pytest.mark.parametrize(
    ("state", "unit"),
    [("-273.15", "°C"), ("-999", "°C"), ("-459.67", "°F"), ("-1", "K")],
    ids=["absolute zero", "a sentinel", "absolute zero in Fahrenheit", "below zero K"],
)
def test_a_temperature_below_absolute_zero_is_unusable(
    hass: HomeAssistant, state: str, unit: str
) -> None:
    """Nothing reads that cold, so it is a sentinel rather than a reading."""
    _set(hass, "sensor.outside", state, {"unit_of_measurement": unit})

    observation = _build(hass, shared={"outdoor_temperature": "sensor.outside"})[
        "outdoor_temperature"
    ]

    assert observation.unusable_reason is UnusableReason.UNCONVERTIBLE


def test_absolute_zero_is_measured_in_the_unit_the_house_reads_in(
    hass: HomeAssistant,
) -> None:
    """-300°F is bitterly cold and perfectly possible; -300°C is not."""
    hass.config.units = US_CUSTOMARY_SYSTEM
    _set(hass, "sensor.outside", "-300", {"unit_of_measurement": "°F"})

    observation = _build(hass, shared={"outdoor_temperature": "sensor.outside"})[
        "outdoor_temperature"
    ]

    assert observation.value == -300

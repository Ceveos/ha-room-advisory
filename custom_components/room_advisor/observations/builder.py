"""Reading Home Assistant's states into one room's observations.

This is the only place Home Assistant's states, units and conventions are
interpreted. Everything downstream sees `Observation` and `GroupObservation`
and knows nothing about entity ids, unit systems or `hvac_action`.

Every observation key is built for every room, whether or not the room has an
entity for it. An input the room lacks is unusable with `NOT_CONFIGURED`,
which is a reading in its own right: it is what tells a guard it was opted out
of rather than broken.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from math import isfinite
from typing import TYPE_CHECKING, Any, Final

from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_NOT_HOME,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.unit_conversion import TemperatureConverter

from ..inputs import INPUTS, InputKey, InputScope, entity_ids
from ..models import GroupObservation, Observation, Observations, UnusableReason

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from homeassistant.core import HomeAssistant, State

# Vocabulary belonging to other integrations, written out rather than
# imported, so that reading a room's state pulls in no component but our own.
# `test_builder_vocabulary.py` holds these against Home Assistant's own enums.
_WEATHER_DOMAIN: Final = "weather"
_ALARM_DOMAIN: Final = "alarm_control_panel"
_TRACKER_DOMAINS: Final = frozenset({"person", "device_tracker"})

_ATTR_WEATHER_TEMPERATURE: Final = "temperature"
_ATTR_WEATHER_TEMPERATURE_UNIT: Final = "temperature_unit"
_ATTR_WEATHER_HUMIDITY: Final = "humidity"
_ATTR_HVAC_ACTION: Final = "hvac_action"

_PERCENT: Final = "%"
_ABSOLUTE_ZERO_C: Final = -273.15

_HVAC_ACTIONS: Final = frozenset(
    {
        "cooling",
        "defrosting",
        "drying",
        "fan",
        "heating",
        "idle",
        "off",
        "preheating",
    }
)
_CONDITIONING_ACTIONS: Final = frozenset({"heating", "cooling"})

_ALARM_STATES: Final = frozenset(
    {
        "armed_away",
        "armed_custom_bypass",
        "armed_home",
        "armed_night",
        "armed_vacation",
        "arming",
        "disarmed",
        "disarming",
        "pending",
        "triggered",
    }
)
_AWAY_ALARM_STATES: Final = frozenset({"armed_away", "armed_vacation"})
"""The armed states that mean nobody is home.

`triggered` is not among them: advice about a window during an alarm is noise.
"""


class _UnreadableError(Exception):
    """Raised while reading an entity that cannot be turned into a reading."""

    def __init__(self, reason: UnusableReason) -> None:
        """Record why the entity could not be read."""
        super().__init__(reason)
        self.reason = reason


type _Reader = Callable[[State], tuple[Any, str | None]]


class _Shape(Enum):
    """How many entities an input holds, and what they add up to."""

    VALUE = auto()
    """One entity, one reading."""

    GROUP = auto()
    """Several entities, kept as members so partial failure is visible."""

    EVERY = auto()
    """Several entities reduced to one reading that all of them must agree on."""


def _as_number(value: Any) -> float:  # noqa: ANN401 - a state or an attribute
    """Read a finite number, or refuse.

    Infinity and NaN are refused as firmly as letters are: they survive
    arithmetic and comparison silently, so a rule would go on to publish
    advice derived from one.
    """
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise _UnreadableError(UnusableReason.UNCONVERTIBLE) from error
    if not isfinite(number):
        raise _UnreadableError(UnusableReason.UNCONVERTIBLE)
    return number


def _as_switch(state: State) -> bool:
    """Read a state that is either on or off."""
    if state.state == STATE_ON:
        return True
    if state.state == STATE_OFF:
        return False
    raise _UnreadableError(UnusableReason.UNCONVERTIBLE)


def _is_present(state: State) -> bool:
    """Read a tracked entity as being somewhere rather than away.

    A tracker reports the zone it is in, so anything other than `not_home` is
    somewhere.
    """
    return state.state != STATE_NOT_HOME


def _read_temperature(state: State) -> tuple[float, str | None]:
    """Read a thermometer, or a weather entity's temperature."""
    if state.domain == _WEATHER_DOMAIN:
        return (
            _as_number(_attribute(state, _ATTR_WEATHER_TEMPERATURE)),
            state.attributes.get(_ATTR_WEATHER_TEMPERATURE_UNIT),
        )
    return _as_number(state.state), state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)


def _read_humidity(state: State) -> tuple[float, str | None]:
    """Read a hygrometer, or a weather entity's humidity.

    A hygrometer that does not report percent is refused rather than read on
    its own scale: a reading of 0.63 is inside every bound a percentage has,
    and taken for one it makes muggy air look bone dry.
    """
    if state.domain == _WEATHER_DOMAIN:
        return _as_number(_attribute(state, _ATTR_WEATHER_HUMIDITY)), _PERCENT
    value, unit = _read_number(state)
    if unit != _PERCENT:
        raise _UnreadableError(UnusableReason.UNCONVERTIBLE)
    return value, unit


def _read_number(state: State) -> tuple[float, str | None]:
    """Read a plain numeric sensor, keeping the unit it reports."""
    return _as_number(state.state), state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)


def _read_switch(state: State) -> tuple[bool, None]:
    """Read an on/off input."""
    return _as_switch(state), None


def _read_occupancy(state: State) -> tuple[bool, None]:
    """Read whether someone is in the room."""
    if state.domain in _TRACKER_DOMAINS:
        return _is_present(state), None
    return _as_switch(state), None


def _read_away(state: State) -> tuple[bool, None]:
    """Read whether one source says the house is empty.

    An alarm panel is away only while armed for an absence. A tracked person
    is away only while in no zone. Anything else is a plain on/off input where
    on means away.
    """
    if state.domain == _ALARM_DOMAIN:
        if state.state not in _ALARM_STATES:
            raise _UnreadableError(UnusableReason.UNCONVERTIBLE)
        return state.state in _AWAY_ALARM_STATES, None
    if state.domain in _TRACKER_DOMAINS:
        return not _is_present(state), None
    return _as_switch(state), None


def _read_conditioning(state: State) -> tuple[bool, None]:
    """Read whether a climate entity is actively heating or cooling.

    `hvac_action` is optional in Home Assistant's climate API, and a
    thermostat that has reached its setpoint is idle while still in heat mode.
    A climate entity that publishes no action is therefore unreadable rather
    than assumed idle.
    """
    action = state.attributes.get(_ATTR_HVAC_ACTION)
    if action not in _HVAC_ACTIONS:
        raise _UnreadableError(UnusableReason.UNCONVERTIBLE)
    return action in _CONDITIONING_ACTIONS, None


def _attribute(state: State, name: str) -> Any:  # noqa: ANN401 - see _as_number
    """Read an attribute an entity is expected to publish."""
    value = state.attributes.get(name)
    if value is None:
        raise _UnreadableError(UnusableReason.UNKNOWN)
    return value


@dataclass(frozen=True, slots=True)
class _Reading:
    """How one configured input becomes one observation."""

    key: str
    shape: _Shape
    read: _Reader
    normalise_temperature: bool = False


_READINGS: Final[Mapping[InputKey, _Reading]] = {
    InputKey.OUTDOOR_TEMPERATURE: _Reading(
        key="outdoor_temperature",
        shape=_Shape.VALUE,
        read=_read_temperature,
        normalise_temperature=True,
    ),
    InputKey.OUTDOOR_HUMIDITY: _Reading(
        key="outdoor_humidity", shape=_Shape.VALUE, read=_read_humidity
    ),
    InputKey.OUTDOOR_AIR_QUALITY: _Reading(
        key="outdoor_air_quality", shape=_Shape.VALUE, read=_read_number
    ),
    InputKey.RAIN_RISK: _Reading(
        key="rain_risk", shape=_Shape.VALUE, read=_read_switch
    ),
    InputKey.AWAY: _Reading(key="away", shape=_Shape.EVERY, read=_read_away),
    InputKey.INDOOR_TEMPERATURE: _Reading(
        key="indoor_temperature",
        shape=_Shape.VALUE,
        read=_read_temperature,
        normalise_temperature=True,
    ),
    InputKey.INDOOR_CO2: _Reading(
        key="indoor_co2", shape=_Shape.VALUE, read=_read_number
    ),
    InputKey.OCCUPANCY: _Reading(
        key="occupancy", shape=_Shape.VALUE, read=_read_occupancy
    ),
    InputKey.WINDOW_CONTACTS: _Reading(
        key="window_contacts", shape=_Shape.GROUP, read=_read_switch
    ),
    InputKey.LIGHTS: _Reading(key="lights", shape=_Shape.GROUP, read=_read_switch),
    InputKey.FAN: _Reading(key="fan", shape=_Shape.VALUE, read=_read_switch),
    InputKey.HVAC: _Reading(
        key="hvac_conditioning", shape=_Shape.VALUE, read=_read_conditioning
    ),
}
"""What each configured input is read as.

The observation key is the input key, except for the climate entity: the input
is a thermostat, the observation is whether it is conditioning the room.
"""

BUILT_KEYS: Final = frozenset(reading.key for reading in _READINGS.values())
"""Every key read from an entity, configured or not."""


def build_observations(
    hass: HomeAssistant,
    shared: Mapping[str, Any],
    room: Mapping[str, Any],
) -> Observations:
    """Read one room, and the house it is in, as of now.

    `shared` is the hub's inputs and `room` is the room's own. Both are the
    stored mappings; an input either holds entity ids or is absent.
    """
    observations: dict[str, Observation] = {}
    groups: dict[str, GroupObservation] = {}

    for spec in INPUTS:
        reading = _READINGS[spec.key]
        stored = shared if spec.scope is InputScope.SHARED else room
        configured = entity_ids(stored, spec.key)
        if reading.shape is _Shape.GROUP:
            groups[reading.key] = _build_group(hass, reading, configured)
        else:
            observations[reading.key] = _build_value(hass, reading, configured)

    return Observations(observations, groups)


def _build_value(
    hass: HomeAssistant, reading: _Reading, configured: list[str]
) -> Observation:
    """Build the one observation an input produces."""
    if not configured:
        return Observation.missing(reading.key, UnusableReason.NOT_CONFIGURED)
    if reading.shape is _Shape.EVERY:
        return _build_every(hass, reading, configured)

    entity_id = configured[0]
    try:
        value, unit = _read(hass, reading, entity_id)
    except _UnreadableError as unreadable:
        return Observation.missing(
            reading.key, unreadable.reason, source_entity_id=entity_id
        )
    return Observation.reading(
        reading.key, value, unit=unit, source_entity_id=entity_id
    )


def _build_every(
    hass: HomeAssistant, reading: _Reading, configured: list[str]
) -> Observation:
    """Build an observation every configured entity has to agree on.

    One unreadable source makes the whole input unreadable, and names the
    source that failed. Half an answer about whether the house is empty is
    worse than none.
    """
    values = []
    for entity_id in configured:
        try:
            value, _ = _read(hass, reading, entity_id)
        except _UnreadableError as unreadable:
            return Observation.missing(
                reading.key, unreadable.reason, source_entity_id=entity_id
            )
        values.append(value)

    return Observation.reading(
        reading.key,
        all(values),
        source_entity_id=configured[0] if len(configured) == 1 else None,
    )


def _build_group(
    hass: HomeAssistant, reading: _Reading, configured: list[str]
) -> GroupObservation:
    """Build a multi-entity input, keeping which member is which.

    An unconfigured input is an empty group, which reports itself unusable.
    """
    known_on: list[str] = []
    known_off: list[str] = []
    unusable: list[str] = []

    for entity_id in configured:
        try:
            value, _ = _read(hass, reading, entity_id)
        except _UnreadableError:
            unusable.append(entity_id)
        else:
            (known_on if value else known_off).append(entity_id)

    return GroupObservation(
        key=reading.key,
        configured=tuple(configured),
        known_on=tuple(known_on),
        known_off=tuple(known_off),
        unusable=tuple(unusable),
    )


def _read(
    hass: HomeAssistant, reading: _Reading, entity_id: str
) -> tuple[Any, str | None]:
    """Read one entity, refusing anything that is not a reading.

    An entity with no state has not reported since startup, which is distinct
    from one reporting that it cannot be read.
    """
    state = hass.states.get(entity_id)
    if state is None:
        raise _UnreadableError(UnusableReason.NOT_YET_SEEN)
    if state.state == STATE_UNAVAILABLE:
        raise _UnreadableError(UnusableReason.UNAVAILABLE)
    if state.state == STATE_UNKNOWN:
        raise _UnreadableError(UnusableReason.UNKNOWN)

    value, unit = reading.read(state)
    if reading.normalise_temperature:
        return _in_system_temperature(hass, value, unit)
    return value, unit


def _in_system_temperature(
    hass: HomeAssistant, value: float, unit: str | None
) -> tuple[float, str]:
    """Convert a temperature into the unit system the user reads in.

    A source that names no unit is refused rather than assumed to be in the
    system's own: a Fahrenheit reading taken for Celsius is wrong by enough to
    advise opening a window in a blizzard. A reading at or below absolute zero
    is refused for the same reason — it is a sentinel, not a temperature.
    """
    target: str = hass.config.units.temperature_unit
    if unit is None:
        raise _UnreadableError(UnusableReason.UNCONVERTIBLE)
    try:
        converted = TemperatureConverter.convert(value, unit, target)
    except HomeAssistantError as error:
        raise _UnreadableError(UnusableReason.UNCONVERTIBLE) from error
    if converted <= TemperatureConverter.convert(
        _ABSOLUTE_ZERO_C, UnitOfTemperature.CELSIUS, target
    ):
        raise _UnreadableError(UnusableReason.UNCONVERTIBLE)
    return converted, target

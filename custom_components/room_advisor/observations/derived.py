"""Observations computed from other observations rather than read from an entity.

A derived observation is usable only when every source it reads is usable.
When one is not, the derivation inherits a reason rather than a bare failure,
because a guard treats "you never configured this" and "this is broken" as
opposite instructions.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, log
from typing import TYPE_CHECKING, Final

from homeassistant.const import UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.unit_conversion import TemperatureConverter

from ..models import Observation, Observations, UnusableReason

if TYPE_CHECKING:
    from collections.abc import Callable

OUTDOOR_DEW_POINT: Final = "outdoor_dew_point"
TEMPERATURE_ADVANTAGE: Final = "temperature_advantage"

_INDOOR_TEMPERATURE: Final = "indoor_temperature"
_OUTDOOR_TEMPERATURE: Final = "outdoor_temperature"
_OUTDOOR_HUMIDITY: Final = "outdoor_humidity"

# Sonntag 1990, in Celsius. Home Assistant's own mold_indicator uses these.
_MAGNUS_B: Final = 17.62
_MAGNUS_C: Final = 243.12

_CELSIUS: Final = UnitOfTemperature.CELSIUS
_PERCENT: Final = "%"


class _UnderivableError(Exception):
    """Raised when every source is readable but cannot be combined."""

    def __init__(self, reason: UnusableReason) -> None:
        """Record why the derivation could not be completed."""
        super().__init__(reason)
        self.reason = reason


def _in_celsius(observation: Observation) -> tuple[float, str]:
    """Convert a temperature to Celsius, which the formulae work in.

    Returns the unit it was read in alongside, which converting proved is one
    the reverse conversion also accepts.
    """
    if observation.unit is None:
        raise _UnderivableError(UnusableReason.UNCONVERTIBLE)
    try:
        celsius = TemperatureConverter.convert(
            float(observation.value), observation.unit, _CELSIUS
        )
    except HomeAssistantError as error:
        raise _UnderivableError(UnusableReason.UNCONVERTIBLE) from error
    return celsius, observation.unit


def _dew_point(sources: tuple[Observation, ...], _margin: float) -> float:
    """Return the outdoor dew point, by the Magnus approximation.

    A relative humidity outside `0 < rh <= 100`, or on a scale other than
    percent, is refused. Zero has no dew point, and 0.63 is a plausible
    fraction that read as a percentage makes muggy air look bone dry.

    The approximation has poles at -243.12°C, which is above absolute zero and
    so reachable from a reading alone, and wherever the numerator's
    coefficient cancels. Both raise rather than divide.
    """
    temperature, humidity = sources
    if humidity.unit != _PERCENT:
        raise _UnderivableError(UnusableReason.UNCONVERTIBLE)
    relative_humidity = float(humidity.value)
    if not 0 < relative_humidity <= 100:
        raise _UnderivableError(UnusableReason.UNCONVERTIBLE)

    celsius, unit = _in_celsius(temperature)
    if _MAGNUS_C + celsius == 0:
        raise _UnderivableError(UnusableReason.UNCONVERTIBLE)
    gamma = log(relative_humidity / 100) + _MAGNUS_B * celsius / (_MAGNUS_C + celsius)
    if _MAGNUS_B - gamma == 0:
        raise _UnderivableError(UnusableReason.UNCONVERTIBLE)
    dew_point = _MAGNUS_C * gamma / (_MAGNUS_B - gamma)
    return TemperatureConverter.convert(dew_point, _CELSIUS, unit)


def _temperature_advantage(sources: tuple[Observation, ...], margin: float) -> float:
    """Return how much cooler outside is than inside, less the margin.

    Both readings already carry the system unit, so the difference is taken
    without conversion. The margin discounts an outdoor source that may be a
    regional forecast rather than a sensor in the garden.
    """
    indoor, outdoor = sources
    return float(indoor.value) - float(outdoor.value) - margin


@dataclass(frozen=True, slots=True)
class _Derivation:
    """One observation computed from others, and the others it reads.

    The first source names the unit the result is reported in.
    """

    key: str
    sources: tuple[str, ...]
    compute: Callable[[tuple[Observation, ...], float], float]


_DERIVATIONS: Final = (
    _Derivation(
        key=OUTDOOR_DEW_POINT,
        sources=(_OUTDOOR_TEMPERATURE, _OUTDOOR_HUMIDITY),
        compute=_dew_point,
    ),
    _Derivation(
        key=TEMPERATURE_ADVANTAGE,
        sources=(_INDOOR_TEMPERATURE, _OUTDOOR_TEMPERATURE),
        compute=_temperature_advantage,
    ),
)

DERIVED_KEYS: Final = frozenset(derivation.key for derivation in _DERIVATIONS)


def _inherited(
    sources: tuple[Observation, ...],
) -> tuple[UnusableReason, str | None] | None:
    """Return the reason and source a derivation takes on, or `None` if usable.

    `not_configured` is the weakest reason and survives only when it is the
    only one present: a derivation with one unconfigured source and one dead
    source is reporting a broken sensor, not a user preference.
    """
    unusable = [
        (source.unusable_reason, source.source_entity_id)
        for source in sources
        if source.unusable_reason is not None
    ]
    if not unusable:
        return None
    for reason, entity_id in unusable:
        if reason is not UnusableReason.NOT_CONFIGURED:
            return reason, entity_id
    return unusable[0]


def _source(observations: Observations, key: str) -> Observation:
    """Read one source, treating one the snapshot never carried as unconfigured.

    A derivation is given whatever the room has, so an absent source is the
    same thing as one the user never configured.
    """
    source = observations.get(key)
    if source is None:
        return Observation.missing(key, UnusableReason.NOT_CONFIGURED)
    return source


def _derive(
    derivation: _Derivation, observations: Observations, margin: float
) -> Observation:
    """Compute one derived observation, or explain why it could not be."""
    sources = tuple(_source(observations, key) for key in derivation.sources)
    inherited = _inherited(sources)
    if inherited is not None:
        reason, source_entity_id = inherited
        return Observation.missing(
            derivation.key, reason, source_entity_id=source_entity_id
        )

    unit = sources[0].unit
    try:
        value = derivation.compute(sources, margin)
    except _UnderivableError as error:
        return Observation.missing(derivation.key, error.reason, unit=unit)
    if not isfinite(value):
        return Observation.missing(
            derivation.key, UnusableReason.UNCONVERTIBLE, unit=unit
        )
    return Observation.reading(derivation.key, value, unit=unit)


def derive_observations(
    observations: Observations, *, uncertainty_margin: float = 0.0
) -> Observations:
    """Return the snapshot with its derived observations added.

    `uncertainty_margin` is the house's allowance for an inaccurate outdoor
    source, in the unit the readings carry.
    """
    derived = dict(observations)
    for derivation in _DERIVATIONS:
        derived[derivation.key] = _derive(derivation, observations, uncertainty_margin)
    return Observations(derived, observations.groups)
